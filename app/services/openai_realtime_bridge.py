from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..domain.statuses import CallResult, CallStatus
from .errors import ProviderConfigurationError, RealtimeBridgeError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RealtimeCallContext:
    batch_id: str
    external_id: str
    attempt_number: int
    client_name: str
    cnpj: str
    phone_dialed: str


@dataclass(slots=True)
class RealtimeBridgeResult:
    batch_id: str | None = None
    external_id: str | None = None
    provider_call_id: str | None = None
    call_status: CallStatus = CallStatus.FAILED
    call_result: CallResult = CallResult.INCONCLUSIVE
    transcript_summary: str | None = None
    observation: str | None = None


@dataclass(slots=True)
class _BridgeState:
    stream_sid: str | None = None
    provider_call_id: str | None = None
    context: RealtimeCallContext | None = None
    user_transcripts: list[str] = field(default_factory=list)
    assistant_transcripts: list[str] = field(default_factory=list)
    classification: CallResult | None = None
    assistant_has_responded: bool = False
    assistant_response_count: int = 0
    latest_output_mark_name: str | None = None
    waiting_close_mark_name: str | None = None
    should_close_twilio: bool = False
    close_twilio_not_before: float | None = None
    observation: str | None = None
    twilio_input_audio_chunks: int = 0
    openai_output_audio_chunks: int = 0
    openai_output_audio_total_base64_chars: int = 0


class OpenAIRealtimeBridgeService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        voice: str,
        transcription_model: str,
        transcription_prompt: str | None,
        noise_reduction_type: str | None = "near_field",
        vad_threshold: float | None = None,
        vad_prefix_padding_ms: int | None = None,
        vad_silence_duration_ms: int | None = None,
        vad_interrupt_response: bool = False,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.transcription_model = transcription_model
        self.transcription_prompt = transcription_prompt
        self.noise_reduction_type = noise_reduction_type
        self.vad_threshold = vad_threshold
        self.vad_prefix_padding_ms = vad_prefix_padding_ms
        self.vad_silence_duration_ms = vad_silence_duration_ms
        self.vad_interrupt_response = vad_interrupt_response

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model and self.voice)

    async def bridge_media_stream(self, twilio_websocket: WebSocket) -> RealtimeBridgeResult:
        logger.info("Aceitando conexao do Twilio Media Stream")
        await twilio_websocket.accept()
        self._ensure_configured()

        state = _BridgeState()
        openai_websocket = None
        openai_listener_task: asyncio.Task[None] | None = None

        try:
            while True:
                loop_time = asyncio.get_running_loop().time()
                if state.waiting_close_mark_name and state.close_twilio_not_before is not None and loop_time >= state.close_twilio_not_before:
                    logger.warning(
                        "Twilio nao confirmou o mark a tempo; encerrando media stream por timeout | batch_id=%s external_id=%s waiting_mark=%s",
                        state.context.batch_id if state.context else None,
                        state.context.external_id if state.context else None,
                        state.waiting_close_mark_name,
                    )
                    state.should_close_twilio = True
                    state.close_twilio_not_before = loop_time

                if state.should_close_twilio:
                    if (
                        state.close_twilio_not_before is None
                        or loop_time >= state.close_twilio_not_before
                    ):
                        logger.info(
                            "Encerrando leitura do Media Stream apos drenagem do audio final | batch_id=%s external_id=%s assistant_response_count=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                            state.assistant_response_count,
                        )
                        break

                try:
                    raw_message = await asyncio.wait_for(
                        twilio_websocket.receive_text(),
                        timeout=0.25,
                    )
                except asyncio.TimeoutError:
                    continue
                except RuntimeError as error:
                    if state.should_close_twilio and "websocket is not connected" in str(error).lower():
                        logger.info(
                            "WebSocket do Twilio ja foi encerrado apos classificacao final | batch_id=%s external_id=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                        )
                        break
                    raise

                payload = self._safe_json(raw_message)
                event_type = payload.get("event")

                if event_type == "connected":
                    logger.info("Twilio Media Stream conectado")
                    continue

                if event_type == "mark":
                    mark_name = ((payload.get("mark") or {}).get("name"))
                    logger.info(
                        "Twilio confirmou reproducao de audio enviado | batch_id=%s external_id=%s mark_name=%s",
                        state.context.batch_id if state.context else None,
                        state.context.external_id if state.context else None,
                        mark_name,
                    )
                    self._handle_twilio_mark(mark_name, state)
                    continue

                if event_type == "start":
                    logger.info("Twilio Media Stream iniciou o fluxo de audio")
                    start_payload = payload.get("start") or {}
                    state.stream_sid = start_payload.get("streamSid") or payload.get("streamSid")
                    state.provider_call_id = start_payload.get("callSid")
                    state.context = self._build_context(start_payload.get("customParameters") or {})
                    logger.info(
                        "Bridge com OpenAI Realtime iniciada | batch_id=%s external_id=%s provider_call_id=%s stream_sid=%s",
                        state.context.batch_id,
                        state.context.external_id,
                        state.provider_call_id,
                        state.stream_sid,
                    )
                    openai_websocket = await websockets.connect(
                        f"wss://api.openai.com/v1/realtime?model={self.model}",
                        additional_headers={
                            "Authorization": f"Bearer {self.api_key}",
                        },
                        max_size=None,
                    )
                    logger.info(
                        "Conexao WebSocket com OpenAI Realtime estabelecida | batch_id=%s external_id=%s model=%s voice=%s",
                        state.context.batch_id,
                        state.context.external_id,
                        self.model,
                        self.voice,
                    )
                    await self._configure_session(openai_websocket, state.context)
                    openai_listener_task = asyncio.create_task(
                        self._forward_openai_events(
                            openai_websocket=openai_websocket,
                            twilio_websocket=twilio_websocket,
                            state=state,
                        )
                    )
                    await self._start_agent_turn(openai_websocket, state.context)
                    continue

                if event_type == "media" and openai_websocket is not None:
                    if state.should_close_twilio or state.waiting_close_mark_name is not None:
                        continue

                    media_payload = payload.get("media") or {}
                    audio_chunk = media_payload.get("payload")
                    if isinstance(audio_chunk, str) and audio_chunk:
                        state.twilio_input_audio_chunks += 1
                        if self._should_log_chunk(state.twilio_input_audio_chunks):
                            logger.info(
                                "Encaminhando audio do Twilio para OpenAI | batch_id=%s external_id=%s chunk_index=%s base64_chars=%s",
                                state.context.batch_id if state.context else None,
                                state.context.external_id if state.context else None,
                                state.twilio_input_audio_chunks,
                                len(audio_chunk),
                            )
                        await openai_websocket.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": audio_chunk,
                                }
                            )
                        )
                    continue

                if event_type == "stop":
                    logger.info(
                        "Twilio Media Stream finalizou o envio de audio | batch_id=%s external_id=%s twilio_input_audio_chunks=%s openai_output_audio_chunks=%s",
                        state.context.batch_id if state.context else None,
                        state.context.external_id if state.context else None,
                        state.twilio_input_audio_chunks,
                        state.openai_output_audio_chunks,
                    )
                    break
        except WebSocketDisconnect:
            logger.info("Twilio fechou a conexao do Media Stream")
            state.observation = state.observation or "Fluxo de audio encerrado pelo Twilio."
        except Exception as error:  # pragma: no cover
            logger.exception("Bridge de voz interrompido por erro inesperado | error=%s", error)
            state.observation = f"Bridge de voz interrompido: {error}"
            raise RealtimeBridgeError(state.observation) from error
        finally:
            if openai_listener_task is not None:
                openai_listener_task.cancel()
            if openai_websocket is not None:
                await openai_websocket.close()
            if openai_listener_task is not None:
                with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                    await openai_listener_task
            if (
                state.should_close_twilio
                and twilio_websocket.client_state == WebSocketState.CONNECTED
            ):
                with contextlib.suppress(RuntimeError):
                    await twilio_websocket.close()

        result = self._build_result(state)
        logger.info(
            "Bridge de voz finalizada | batch_id=%s external_id=%s provider_call_id=%s call_status=%s call_result=%s twilio_input_audio_chunks=%s openai_output_audio_chunks=%s",
            result.batch_id,
            result.external_id,
            result.provider_call_id,
            result.call_status,
            result.call_result,
            state.twilio_input_audio_chunks,
            state.openai_output_audio_chunks,
        )
        return result

    async def _configure_session(
        self,
        openai_websocket: Any,
        context: RealtimeCallContext,
    ) -> None:
        logger.info(
            "Enviando session.update para OpenAI Realtime | batch_id=%s external_id=%s voice=%s model=%s transcription_model=%s noise_reduction=%s vad_threshold=%s vad_prefix_padding_ms=%s vad_silence_duration_ms=%s vad_interrupt_response=%s",
            context.batch_id,
            context.external_id,
            self.voice,
            self.model,
            self.transcription_model,
            self.noise_reduction_type,
            self.vad_threshold,
            self.vad_prefix_padding_ms,
            self.vad_silence_duration_ms,
            self.vad_interrupt_response,
        )
        transcription_config: dict[str, Any] = {
            "model": self.transcription_model,
            "language": "pt",
        }
        if self.transcription_prompt:
            transcription_config["prompt"] = self.transcription_prompt

        turn_detection_config: dict[str, Any] = {
            "type": "server_vad",
            "interrupt_response": self.vad_interrupt_response,
            "create_response": True,
        }
        if self.vad_threshold is not None:
            turn_detection_config["threshold"] = self.vad_threshold
        if self.vad_prefix_padding_ms is not None:
            turn_detection_config["prefix_padding_ms"] = self.vad_prefix_padding_ms
        if self.vad_silence_duration_ms is not None:
            turn_detection_config["silence_duration_ms"] = self.vad_silence_duration_ms

        input_audio_config: dict[str, Any] = {
            "format": {"type": "audio/pcmu"},
            "transcription": transcription_config,
            "turn_detection": turn_detection_config,
        }
        if self.noise_reduction_type:
            input_audio_config["noise_reduction"] = {"type": self.noise_reduction_type}

        await openai_websocket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": self._build_instructions(context),
                        "audio": {
                            "input": input_audio_config,
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": self.voice,
                            },
                        },
                    },
                }
            )
        )

    async def _start_agent_turn(
        self,
        openai_websocket: Any,
        context: RealtimeCallContext,
    ) -> None:
        logger.info(
            "Iniciando prompt da ligacao no OpenAI Realtime | batch_id=%s external_id=%s",
            context.batch_id,
            context.external_id,
        )
        await openai_websocket.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Inicie agora a ligacao, em portugues do Brasil, e valide se o numero "
                                    f"{context.phone_dialed} pertence a empresa {context.client_name}, CNPJ {context.cnpj}."
                                ),
                            }
                        ],
                    },
                }
            )
        )
        await openai_websocket.send(json.dumps({"type": "response.create"}))

    async def _forward_openai_events(
        self,
        *,
        openai_websocket: Any,
        twilio_websocket: WebSocket,
        state: _BridgeState,
    ) -> None:
        async for raw_message in openai_websocket:
            event = self._safe_json(raw_message)
            event_type = event.get("type")

            if event_type in {"session.created", "session.updated", "response.created"}:
                logger.info(
                    "Evento do OpenAI Realtime recebido | batch_id=%s external_id=%s event_type=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    event_type,
                )
                continue

            if event_type == "response.output_audio.delta":
                delta = event.get("delta")
                if (
                    isinstance(delta, str)
                    and delta
                    and state.stream_sid
                    and twilio_websocket.client_state == WebSocketState.CONNECTED
                ):
                    state.openai_output_audio_chunks += 1
                    state.openai_output_audio_total_base64_chars += len(delta)
                    if self._should_log_chunk(state.openai_output_audio_chunks):
                        logger.info(
                            "Recebido audio da OpenAI e reenviando ao Twilio | batch_id=%s external_id=%s chunk_index=%s base64_chars=%s total_base64_chars=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                            state.openai_output_audio_chunks,
                            len(delta),
                            state.openai_output_audio_total_base64_chars,
                        )
                    try:
                        await twilio_websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": state.stream_sid,
                                    "media": {"payload": delta},
                                }
                            )
                        )
                    except RuntimeError as error:
                        if state.should_close_twilio:
                            logger.info(
                                "Ignorando envio de audio ao Twilio apos fechamento solicitado | batch_id=%s external_id=%s error=%s",
                                state.context.batch_id if state.context else None,
                                state.context.external_id if state.context else None,
                                error,
                            )
                            break
                        raise
                continue

            if event_type == "response.output_audio.done":
                logger.info(
                    "OpenAI Realtime finalizou emissao de audio | batch_id=%s external_id=%s output_audio_chunks=%s total_base64_chars=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    state.openai_output_audio_chunks,
                    state.openai_output_audio_total_base64_chars,
                )
                await self._send_twilio_mark_for_current_audio(twilio_websocket, state)
                continue

            if event_type == "response.output_audio_transcript.done":
                transcript = event.get("transcript")
                logger.info(
                    "Transcricao final do audio de resposta da OpenAI | batch_id=%s external_id=%s transcript=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    transcript,
                )
                if isinstance(transcript, str) and transcript.strip():
                    cleaned_transcript = transcript.strip()
                    state.assistant_transcripts.append(cleaned_transcript)
                    if state.classification is None:
                        state.classification = self._classify_assistant_transcript(cleaned_transcript)
                        logger.info(
                            "Classificacao automatica pela fala do agente | classification=%s",
                            state.classification,
                        )
                        await self._maybe_close_twilio_stream(twilio_websocket, state)
                continue

            if event_type == "response.done":
                logger.info(
                    "OpenAI Realtime concluiu uma resposta de audio | batch_id=%s external_id=%s output_audio_chunks=%s twilio_input_audio_chunks=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    state.openai_output_audio_chunks,
                    state.twilio_input_audio_chunks,
                )
                state.assistant_has_responded = True
                state.assistant_response_count += 1
                await self._maybe_close_twilio_stream(twilio_websocket, state)
                continue

            if event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript")
                if isinstance(transcript, str) and transcript.strip():
                    cleaned_transcript = transcript.strip()
                    state.user_transcripts.append(cleaned_transcript)
                    logger.info(
                        "Transcricao recebida do OpenAI Realtime | transcript=%s",
                        cleaned_transcript,
                    )
                    if state.classification is None:
                        state.classification = self._classify_transcript(cleaned_transcript)
                        logger.info(
                            "Classificacao automatica do transcript | classification=%s",
                            state.classification,
                        )
                        await self._maybe_close_twilio_stream(twilio_websocket, state)
                continue

            if event_type == "error":
                logger.error(
                    "OpenAI Realtime retornou erro | batch_id=%s external_id=%s payload=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    event,
                )
                state.observation = "OpenAI Realtime retornou erro durante o bridge de audio."
                continue

    def _build_context(self, custom_parameters: dict[str, Any]) -> RealtimeCallContext:
        try:
            return RealtimeCallContext(
                batch_id=str(custom_parameters.get("batch_id") or ""),
                external_id=str(custom_parameters.get("external_id") or ""),
                attempt_number=int(custom_parameters.get("attempt_number") or 1),
                client_name=str(custom_parameters.get("client_name") or "Cliente sem nome"),
                cnpj=str(custom_parameters.get("cnpj") or ""),
                phone_dialed=str(custom_parameters.get("phone_dialed") or ""),
            )
        except (TypeError, ValueError) as error:
            raise RealtimeBridgeError("Parametros do Twilio Media Stream invalidos.") from error

    def _build_result(self, state: _BridgeState) -> RealtimeBridgeResult:
        transcript_parts: list[str] = []
        if state.user_transcripts:
            transcript_parts.append(f"cliente: {' '.join(state.user_transcripts)}")
        if state.assistant_transcripts:
            transcript_parts.append(f"agente: {' '.join(state.assistant_transcripts)}")
        transcript_summary = " | ".join(transcript_parts) if transcript_parts else None
        context = state.context
        if context is None:
            return RealtimeBridgeResult(
                provider_call_id=state.provider_call_id,
                call_status=CallStatus.FAILED,
                call_result=CallResult.INCONCLUSIVE,
                transcript_summary=transcript_summary,
                observation=state.observation or "Media Stream recebido sem contexto valido.",
            )

        if state.classification == CallResult.CONFIRMED:
            return RealtimeBridgeResult(
                batch_id=context.batch_id,
                external_id=context.external_id,
                provider_call_id=state.provider_call_id,
                call_status=CallStatus.ANSWERED,
                call_result=CallResult.CONFIRMED,
                transcript_summary=transcript_summary,
                observation="Ligacao confirmada por resposta positiva do atendente.",
            )

        if state.classification == CallResult.REJECTED:
            return RealtimeBridgeResult(
                batch_id=context.batch_id,
                external_id=context.external_id,
                provider_call_id=state.provider_call_id,
                call_status=CallStatus.ANSWERED,
                call_result=CallResult.REJECTED,
                transcript_summary=transcript_summary,
                observation="Ligacao marcou o numero atual como nao pertencente ao cliente.",
            )

        if state.assistant_has_responded and state.openai_output_audio_chunks == 0:
            state.observation = (
                state.observation
                or "OpenAI Realtime respondeu sem chunks de audio de saida para o Twilio."
            )

        return RealtimeBridgeResult(
            batch_id=context.batch_id,
            external_id=context.external_id,
            provider_call_id=state.provider_call_id,
            call_status=CallStatus.ANSWERED if transcript_summary else CallStatus.FAILED,
            call_result=CallResult.INCONCLUSIVE,
            transcript_summary=transcript_summary,
            observation=state.observation or "Ligacao concluida sem classificacao automatica definitiva.",
        )

    def _build_instructions(self, context: RealtimeCallContext) -> str:
        return (
            "Voce e uma agente de voz de validacao cadastral em portugues do Brasil, com tom caloroso, natural, humano e com voz feminina suave. "
            "Fale como uma atendente brasileira cordial em uma ligacao curta, sem soar robotica. "
            "Seu unico objetivo e validar se o telefone atual pertence ao cliente informado. "
            "Apresente-se brevemente, diga que esta validando o cadastro e faca uma pergunta objetiva. "
            "Peca uma resposta curta, de preferencia SIM se o numero pertence ao cliente ou NAO se nao pertence. "
            "Cliente: "
            f"{context.client_name}. "
            f"CNPJ: {context.cnpj}. "
            "Se a resposta for positiva, agradeca e informe que a validacao foi concluida. "
            "Se a resposta for negativa, agradeca e diga que o cadastro sera atualizado. "
            "Se a resposta estiver confusa, faca no maximo uma repergunta curta. "
            "Use frases curtas, ritmo natural e linguagem apropriada para telefone."
        )

    def _classify_transcript(self, transcript: str) -> CallResult | None:
        normalized = self._normalize_text(transcript)
        negative_signals = [
            "nao",
            "numero errado",
            "numero incorreto",
            "nao pertence",
            "nao conheco",
            "desconheco",
            "nao e da empresa",
            "nao sei informar",
        ]
        positive_signals = [
            "sim",
            "confirmo",
            "confirma",
            "correto",
            "esta correto",
            "ta correto",
            "pertence",
            "e da empresa",
            "continua sendo",
            "isso mesmo",
        ]

        if self._contains_any_signal(normalized, negative_signals):
            return CallResult.REJECTED

        if self._contains_any_signal(normalized, positive_signals):
            return CallResult.CONFIRMED

        return None

    def _classify_assistant_transcript(self, transcript: str) -> CallResult | None:
        normalized = self._normalize_text(transcript)
        negative_signals = [
            "cadastro sera atualizado",
            "numero nao pertence",
            "numero incorreto",
            "numero nao confirmado",
            "validacao nao concluida",
        ]
        positive_signals = [
            "obrigado pela confirmacao",
            "validacao concluida",
            "contato confirmado",
            "numero confirmado",
        ]

        if self._contains_any_signal(normalized, negative_signals):
            return CallResult.REJECTED

        if self._contains_any_signal(normalized, positive_signals):
            return CallResult.CONFIRMED

        return None

    async def _maybe_close_twilio_stream(
        self,
        twilio_websocket: WebSocket,
        state: _BridgeState,
    ) -> None:
        del twilio_websocket

        if state.classification is None or state.assistant_response_count < 2:
            return

        if state.latest_output_mark_name:
            state.waiting_close_mark_name = state.latest_output_mark_name
            state.close_twilio_not_before = asyncio.get_running_loop().time() + 5.0
            logger.info(
                "Fechamento gracioso do Media Stream aguardando confirmacao de reproducao do Twilio | batch_id=%s external_id=%s assistant_response_count=%s classification=%s waiting_mark=%s timeout_at=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                state.assistant_response_count,
                state.classification,
                state.waiting_close_mark_name,
                state.close_twilio_not_before,
            )
            return

        state.should_close_twilio = True
        state.close_twilio_not_before = asyncio.get_running_loop().time() + 2.5
        logger.info(
            "Fechamento gracioso do Media Stream agendado sem mark do Twilio | batch_id=%s external_id=%s assistant_response_count=%s classification=%s close_not_before=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            state.assistant_response_count,
            state.classification,
            state.close_twilio_not_before,
        )

    async def _send_twilio_mark_for_current_audio(
        self,
        twilio_websocket: WebSocket,
        state: _BridgeState,
    ) -> None:
        if not state.stream_sid or twilio_websocket.client_state != WebSocketState.CONNECTED:
            return

        mark_name = f"assistant-response-{state.assistant_response_count + 1}-{state.openai_output_audio_chunks}"
        state.latest_output_mark_name = mark_name
        await twilio_websocket.send_text(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": state.stream_sid,
                    "mark": {"name": mark_name},
                }
            )
        )
        logger.info(
            "Mark enviado ao Twilio para confirmar reproducao do audio final | batch_id=%s external_id=%s mark_name=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            mark_name,
        )

    def _handle_twilio_mark(
        self,
        mark_name: str | None,
        state: _BridgeState,
    ) -> None:
        if not mark_name or state.waiting_close_mark_name != mark_name:
            return

        state.should_close_twilio = True
        state.close_twilio_not_before = asyncio.get_running_loop().time()
        logger.info(
            "Fechamento gracioso liberado apos confirmacao mark do Twilio | batch_id=%s external_id=%s mark_name=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            mark_name,
        )

    def _contains_any_signal(self, normalized: str, signals: list[str]) -> bool:
        padded_text = f" {normalized} "
        return any(f" {signal} " in padded_text for signal in signals)

    def _normalize_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_text = "".join(
            character
            for character in normalized.lower()
            if not unicodedata.combining(character)
        )
        sanitized = "".join(
            character if character.isalnum() or character.isspace() else " "
            for character in ascii_text
        )
        return " ".join(sanitized.split())

    def _safe_json(self, raw_message: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError as error:
            raise RealtimeBridgeError("Mensagem JSON invalida recebida no media stream.") from error

        if not isinstance(payload, dict):
            raise RealtimeBridgeError("Mensagem inesperada recebida no media stream.")
        return payload

    def _ensure_configured(self) -> None:
        if self.is_configured():
            return
        raise ProviderConfigurationError(
            "OpenAI Realtime",
            "defina OPENAI_API_KEY, OPENAI_REALTIME_MODEL e OPENAI_REALTIME_VOICE.",
        )

    def _should_log_chunk(self, chunk_index: int) -> bool:
        return chunk_index <= 3 or chunk_index % 25 == 0
