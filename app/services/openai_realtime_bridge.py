from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..domain.statuses import CallResult, CallStatus
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..utils.security import decrypt_provider_secret
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
    caller_company_name: str | None = None
    workflow_kind: str | None = None
    segment_name: str | None = None
    callback_phone: str | None = None
    callback_contact_name: str | None = None
    resolved_api_key: str | None = None
    resolved_model: str | None = None
    resolved_voice: str | None = None
    resolved_output_speed: float | None = None
    resolved_style_instructions: str | None = None
    realtime_model_override: str | None = None
    realtime_voice_override: str | None = None
    realtime_output_speed_override: float | None = None
    realtime_style_profile: str | None = None


@dataclass(slots=True)
class RealtimeBridgeResult:
    batch_id: str | None = None
    external_id: str | None = None
    provider_call_id: str | None = None
    call_status: CallStatus = CallStatus.FAILED
    call_result: CallResult = CallResult.INCONCLUSIVE
    transcript_summary: str | None = None
    observation: str | None = None
    terminate_provider_call: bool = False


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
    last_assistant_response_classification: CallResult | None = None
    assistant_signaled_goodbye: bool = False
    openai_response_active: bool = False
    pending_response_create: bool = False
    pending_response_instruction: str | None = None
    classification_source: str | None = None
    close_after_assistant_response_count: int | None = None
    latest_output_mark_name: str | None = None
    waiting_close_mark_name: str | None = None
    should_close_twilio: bool = False
    close_twilio_not_before: float | None = None
    ignore_twilio_audio_until: float | None = None
    ignore_twilio_audio_until_mark_name: str | None = None
    pending_cadastral_confirmation_question: bool = False
    cadastral_confirmation_response_received: bool = False
    pending_supplier_question: str | None = None
    supplier_phone_belongs_confirmed: bool = False
    supplier_supplies_segment_confirmed: bool = False
    supplier_callback_accept_confirmed: bool = False
    supplier_rejection_reason: str | None = None
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
        output_speed: float | None,
        temperature: float | None,
        max_response_output_tokens: int | None,
        style_instructions: str | None,
        transcription_model: str,
        transcription_prompt: str | None,
        noise_reduction_type: str | None = "near_field",
        vad_threshold: float | None = None,
        vad_prefix_padding_ms: int | None = None,
        vad_silence_duration_ms: int | None = None,
        vad_interrupt_response: bool = False,
        batch_repository: ValidationBatchRepository | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.output_speed = output_speed
        self.temperature = temperature
        self.max_response_output_tokens = max_response_output_tokens
        self.style_instructions = style_instructions
        self.transcription_model = transcription_model
        self.transcription_prompt = transcription_prompt
        self.noise_reduction_type = noise_reduction_type
        self.vad_threshold = vad_threshold
        self.vad_prefix_padding_ms = vad_prefix_padding_ms
        self.vad_silence_duration_ms = vad_silence_duration_ms
        self.vad_interrupt_response = vad_interrupt_response
        self.batch_repository = batch_repository

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model and self.voice)

    async def bridge_media_stream(self, twilio_websocket: WebSocket) -> RealtimeBridgeResult:
        logger.info("Aceitando conexao do Twilio Media Stream")
        await twilio_websocket.accept()

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
                    self._hydrate_context_from_batch(state.context)
                    self._ensure_runtime_configured(state.context)
                    logger.info(
                        "Bridge com OpenAI Realtime iniciada | batch_id=%s external_id=%s provider_call_id=%s stream_sid=%s",
                        state.context.batch_id,
                        state.context.external_id,
                        state.provider_call_id,
                        state.stream_sid,
                    )
                    openai_websocket = await websockets.connect(
                        f"wss://api.openai.com/v1/realtime?model={self._resolve_model(state.context)}",
                        additional_headers={
                            "Authorization": f"Bearer {self._resolve_api_key(state.context)}",
                        },
                        max_size=None,
                    )
                    logger.info(
                        "Conexao WebSocket com OpenAI Realtime estabelecida | batch_id=%s external_id=%s model=%s voice=%s",
                        state.context.batch_id,
                        state.context.external_id,
                        self._resolve_model(state.context),
                        self._resolve_voice(state.context),
                    )
                    await self._configure_session(openai_websocket, state.context)
                    openai_listener_task = asyncio.create_task(
                        self._forward_openai_events(
                            openai_websocket=openai_websocket,
                            twilio_websocket=twilio_websocket,
                            state=state,
                        )
                    )
                    await self._start_agent_turn(openai_websocket, state.context, state)
                    continue

                if event_type == "media" and openai_websocket is not None:
                    if state.should_close_twilio or state.waiting_close_mark_name is not None:
                        continue

                    loop_time = asyncio.get_running_loop().time()
                    if state.ignore_twilio_audio_until_mark_name is not None:
                        continue
                    if (
                        state.ignore_twilio_audio_until is not None
                        and loop_time < state.ignore_twilio_audio_until
                    ):
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
                with contextlib.suppress(asyncio.TimeoutError, RuntimeError):
                    await asyncio.wait_for(openai_websocket.close(), timeout=1.0)
            if openai_listener_task is not None:
                with contextlib.suppress(
                    asyncio.CancelledError,
                    asyncio.TimeoutError,
                    RuntimeError,
                ):
                    await asyncio.wait_for(openai_listener_task, timeout=1.0)
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
            "Enviando session.update para OpenAI Realtime | batch_id=%s external_id=%s voice=%s output_speed=%s model=%s transcription_model=%s noise_reduction=%s vad_threshold=%s vad_prefix_padding_ms=%s vad_silence_duration_ms=%s vad_interrupt_response=%s",
            context.batch_id,
            context.external_id,
            self._resolve_voice(context),
            self._resolve_output_speed(context),
            self._resolve_model(context),
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
            "create_response": False,
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

        output_audio_config: dict[str, Any] = {
            "format": {"type": "audio/pcmu"},
            "voice": self._resolve_voice(context),
        }
        resolved_output_speed = self._resolve_output_speed(context)
        if resolved_output_speed is not None:
            output_audio_config["speed"] = resolved_output_speed

        session_config: dict[str, Any] = {
            "type": "realtime",
            "instructions": self._build_instructions(context),
            "audio": {
                "input": input_audio_config,
                "output": output_audio_config,
            },
        }
        await openai_websocket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": session_config,
                }
            )
        )

    async def _start_agent_turn(
        self,
        openai_websocket: Any,
        context: RealtimeCallContext,
        state: _BridgeState,
    ) -> None:
        logger.info(
            "Iniciando prompt da ligacao no OpenAI Realtime | batch_id=%s external_id=%s workflow_kind=%s",
            context.batch_id,
            context.external_id,
            context.workflow_kind or "cadastral_validation",
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
                                "text": self._build_initial_turn_prompt(context),
                            }
                        ],
                    },
                }
            )
        )
        await self._request_openai_response(openai_websocket, state, allow_defer=False)

    async def _request_openai_response(
        self,
        openai_websocket: Any,
        state: _BridgeState,
        *,
        allow_defer: bool,
    ) -> bool:
        if allow_defer and state.openai_response_active:
            state.pending_response_create = True
            logger.info(
                "Resposta da IA adiada ate o termino da resposta atual | batch_id=%s external_id=%s assistant_response_count=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                state.assistant_response_count,
            )
            return False

        state.pending_response_create = False
        if state.pending_response_instruction:
            logger.info(
                "Injetando instrucao curta antes da proxima resposta da IA | batch_id=%s external_id=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
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
                                    "text": state.pending_response_instruction,
                                }
                            ],
                        },
                    }
                )
            )
            state.pending_response_instruction = None
        state.openai_response_active = True
        await openai_websocket.send(json.dumps({"type": "response.create"}))
        return True

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

            if event_type in {"session.created", "session.updated"}:
                logger.info(
                    "Evento do OpenAI Realtime recebido | batch_id=%s external_id=%s event_type=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    event_type,
                )
                continue

            if event_type == "response.created":
                state.openai_response_active = True
                state.last_assistant_response_classification = None
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
                    if state.context is not None and state.context.workflow_kind == "supplier_validation":
                        self._capture_supplier_question_state(cleaned_transcript, state)
                    else:
                        self._capture_cadastral_question_state(cleaned_transcript, state)
                    if self._assistant_transcript_signals_final_goodbye(cleaned_transcript):
                        state.assistant_signaled_goodbye = True
                        logger.info(
                            "Despedida final da assistente detectada | batch_id=%s external_id=%s transcript=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                            cleaned_transcript,
                        )
                    classification = self._classify_assistant_transcript(
                        cleaned_transcript,
                        state=state,
                    )
                    if not self._should_accept_assistant_classification(
                        classification,
                        state=state,
                    ):
                        logger.info(
                            "Classificacao pela fala da assistente ignorada por falta de confirmacao previa do cliente | batch_id=%s external_id=%s classification=%s transcript=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                            classification,
                            cleaned_transcript,
                        )
                        classification = None
                    logger.info(
                        "Classificacao automatica pela fala do agente | classification=%s",
                        classification,
                    )
                    state.last_assistant_response_classification = classification
                    self._register_classification(
                        classification,
                        source="assistant",
                        state=state,
                    )
                continue

            if event_type == "response.done":
                logger.info(
                    "OpenAI Realtime concluiu uma resposta de audio | batch_id=%s external_id=%s output_audio_chunks=%s twilio_input_audio_chunks=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    state.openai_output_audio_chunks,
                    state.twilio_input_audio_chunks,
                )
                state.openai_response_active = False
                state.assistant_has_responded = True
                state.assistant_response_count += 1
                should_reopen_user_capture = (
                    not state.assistant_signaled_goodbye
                    and state.classification is None
                    and state.waiting_close_mark_name is None
                    and not state.should_close_twilio
                )
                if state.latest_output_mark_name and should_reopen_user_capture:
                    state.ignore_twilio_audio_until_mark_name = state.latest_output_mark_name
                    state.ignore_twilio_audio_until = None
                elif should_reopen_user_capture:
                    state.ignore_twilio_audio_until = asyncio.get_running_loop().time() + 0.8
                else:
                    state.ignore_twilio_audio_until_mark_name = None
                    state.ignore_twilio_audio_until = None
                if state.pending_response_create:
                    logger.info(
                        "Disparando resposta pendente da IA apos termino da resposta anterior | batch_id=%s external_id=%s assistant_response_count=%s",
                        state.context.batch_id if state.context else None,
                        state.context.external_id if state.context else None,
                        state.assistant_response_count,
                    )
                    await self._request_openai_response(
                        openai_websocket,
                        state,
                        allow_defer=False,
                    )
                if state.assistant_signaled_goodbye:
                    state.pending_response_create = False
                    self._request_graceful_close_after_current_audio(
                        state,
                        reason="despedida final da assistente",
                    )
                    continue
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
                    classification = self._classify_transcript(
                        cleaned_transcript,
                        state.context,
                        state=state,
                    )
                    logger.info(
                        "Classificacao automatica do transcript | classification=%s",
                        classification,
                    )
                    if (
                        state.pending_cadastral_confirmation_question
                        and self._is_substantive_cadastral_confirmation_reply(cleaned_transcript)
                    ):
                        state.cadastral_confirmation_response_received = True
                    self._register_classification(
                        classification,
                        source="user",
                        state=state,
                    )
                    if self._should_create_response_for_user_transcript(
                        cleaned_transcript,
                        state=state,
                    ):
                        logger.info(
                            "Disparando resposta manual da IA apos transcricao valida do usuario | batch_id=%s external_id=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                        )
                        await self._request_openai_response(
                            openai_websocket,
                            state,
                            allow_defer=True,
                        )
                    else:
                        logger.info(
                            "Ignorando transcricao ambigua ou ruido antes de gerar nova resposta | batch_id=%s external_id=%s transcript=%s",
                            state.context.batch_id if state.context else None,
                            state.context.external_id if state.context else None,
                            cleaned_transcript,
                        )
                continue

            if event_type == "error":
                error_payload = event.get("error") or {}
                if error_payload.get("code") == "conversation_already_has_active_response":
                    state.pending_response_create = True
                    logger.warning(
                        "OpenAI ainda esta concluindo a resposta anterior; nova resposta sera disparada apos o termino da atual | batch_id=%s external_id=%s",
                        state.context.batch_id if state.context else None,
                        state.context.external_id if state.context else None,
                    )
                    continue

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
                caller_company_name=self._parse_optional_string(custom_parameters.get("caller_company_name")),
                workflow_kind=self._parse_optional_string(custom_parameters.get("workflow_kind")) or "cadastral_validation",
                segment_name=self._parse_optional_string(custom_parameters.get("segment_name")),
                callback_phone=self._parse_optional_string(custom_parameters.get("callback_phone")),
                callback_contact_name=self._parse_optional_string(custom_parameters.get("callback_contact_name")),
                realtime_model_override=self._parse_optional_string(custom_parameters.get("realtime_model")),
                realtime_voice_override=self._parse_optional_string(custom_parameters.get("realtime_voice")),
                realtime_output_speed_override=self._parse_optional_float(custom_parameters.get("realtime_output_speed")),
                realtime_style_profile=self._parse_optional_string(custom_parameters.get("realtime_style_profile")),
            )
        except (TypeError, ValueError) as error:
            raise RealtimeBridgeError("Parametros do Twilio Media Stream invalidos.") from error

    def _build_result(self, state: _BridgeState) -> RealtimeBridgeResult:
        terminate_provider_call = self._should_terminate_provider_call(state)
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
                terminate_provider_call=terminate_provider_call,
            )

        if state.classification == CallResult.REJECTED:
            return RealtimeBridgeResult(
                batch_id=context.batch_id,
                external_id=context.external_id,
                provider_call_id=state.provider_call_id,
                call_status=CallStatus.ANSWERED,
                call_result=CallResult.REJECTED,
                transcript_summary=transcript_summary,
                observation=self._rejected_observation_for_state(state),
                terminate_provider_call=terminate_provider_call,
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
            observation=state.observation or "Ligação concluida sem classificacao automatica definitiva.",
            terminate_provider_call=terminate_provider_call,
        )

    def _rejected_observation_for_state(self, state: _BridgeState) -> str:
        if state.context is not None and state.context.workflow_kind == "supplier_validation":
            if state.supplier_rejection_reason == "phone_belongs":
                return "Ligação confirmou que o numero atual não pertence a empresa."
            if state.supplier_rejection_reason == "supplies_segment":
                return "Ligação confirmou que a empresa não fornece o segmento informado."
            if state.supplier_rejection_reason == "commercial_interest":
                return "Ligação confirmou que o contato não aceita retorno comercial."
        return "Ligação marcou o numero atual como não pertencente ao cliente."

    def _build_supplier_rejection_close_prompt(self, state: _BridgeState) -> str:
        reason = state.supplier_rejection_reason
        if reason == "phone_belongs":
            return (
                "O cliente informou que este contato nao pertence a empresa. "
                "Agora responda apenas com um agradecimento curto e uma despedida final. "
                "Nao faca nenhuma nova pergunta e encerre a chamada."
            )
        if reason == "supplies_segment":
            return (
                "O cliente informou que a empresa nao fornece o segmento validado. "
                "Agora responda apenas com um agradecimento curto e uma despedida final. "
                "Nao faca nenhuma nova pergunta e encerre a chamada."
            )
        if reason == "commercial_interest":
            return (
                "O cliente informou que esse contato nao aceita retorno comercial. "
                "Agora responda apenas com um agradecimento curto e uma despedida final. "
                "Nao faca nenhuma nova pergunta e encerre a chamada."
            )
        return (
            "O cliente respondeu negativamente ao ponto validado. "
            "Agora responda apenas com um agradecimento curto e uma despedida final. "
            "Nao faca nenhuma nova pergunta e encerre a chamada."
        )

    def _supplier_user_rejection_goodbye_can_close(self, state: _BridgeState) -> bool:
        return (
            state.context is not None
            and state.context.workflow_kind == "supplier_validation"
            and state.classification == CallResult.REJECTED
            and state.classification_source == "user"
            and state.assistant_signaled_goodbye
        )

    def _build_instructions(self, context: RealtimeCallContext) -> str:
        caller_company_name = context.caller_company_name or "Central de Validacao Cadastral"
        if context.workflow_kind == "supplier_validation":
            segment_name = context.segment_name or "o segmento informado"
            instructions = (
                "Voce e uma agente de voz de qualificacao de fornecedores em portugues do Brasil. "
                "Fale como uma atendente brasileira cordial, clara e profissional, sem soar robotica. "
                "Conduza a ligacao como um fluxo linear e curto, com uma pergunta por vez. "
                "Na primeira fala, apenas cumprimente, pergunte se esta tudo bem e espere a resposta do cliente. "
                "Nao responda voce mesma ao cumprimento antes da pessoa falar. "
                f"Depois se identifique somente em nome da empresa {caller_company_name}, sem dizer nome proprio. "
                "Nao diga nome proprio. "
                f"Explique que esta validando fornecedores do segmento {segment_name}. "
                "Faca exatamente uma pergunta de negocio por vez e sempre espere a resposta do cliente antes de continuar. "
                "Os tres pontos a confirmar sao: se esse numero pertence a empresa, se a empresa fornece o segmento e se pode receber retorno comercial por esse contato. "
                "Nunca junte confirmacao de numero, segmento e retorno comercial na mesma pergunta. "
                "Nunca responda pelo cliente e nunca repita o numero de telefone em voz alta. "
                "Nao cite CNPJ por padrao. "
                "Se a pessoa fizer uma pergunta ou desviar do assunto, responda em no maximo uma frase curta e retome exatamente o ponto pendente. "
                "Se a resposta vier ambigua, contraditoria ou responder a um ponto diferente do que foi perguntado, peca uma confirmacao curta do mesmo ponto antes de avancar. "
                "Nao invente confirmacoes e nao deduza o proximo passo a partir de silencio ou de conversa social. "
                "Se qualquer um dos tres pontos vier negativo, agradeca, encerre a ligacao e nao siga para as proximas perguntas. "
                "Quando o terceiro ponto estiver confirmado, agradeca, faca uma despedida curta, encerre a chamada sem aguardar nova resposta do cliente e nao abra uma nova pergunta."
            )
        else:
            instructions = (
                "Voce e uma agente de voz de validacao cadastral em portugues do Brasil, com tom caloroso, natural e humano. "
                "Fale como uma atendente brasileira cordial em uma ligacao curta, sem soar robotica. "
                "Conduza a ligacao de forma objetiva, com uma pergunta por vez. "
                "Na primeira fala, apenas cumprimente, pergunte se esta tudo bem e espere a resposta do cliente. "
                "Nunca diga estou bem e voce antes do cliente responder. "
                "Somente depois da resposta da pessoa, se fizer sentido, responda brevemente ao cumprimento e espere a pessoa responder antes de explicar o motivo da ligacao. "
                f"Depois se apresente brevemente em nome da empresa {caller_company_name}, sem dizer nome proprio, "
                f"e explique que esta validando o cadastro da empresa {context.client_name} para manter os contatos atualizados. "
                "Seu unico objetivo e validar se esse contato pertence ao cliente informado. "
                "Faca apenas uma pergunta por vez e, depois de perguntar se o contato pertence a empresa, aguarde a resposta do cliente antes de continuar. "
                "Se a pessoa ficar em silencio ou responder apenas ao cumprimento, nao conclua a validacao e nao invente uma confirmacao. "
                "Nao leia nem repita o numero de telefone em voz alta e nao cite CNPJ por padrao. "
                "Se a pessoa perguntar por que precisa confirmar o numero ou desviar do assunto, responda brevemente e retome a validacao. "
                "perguntas laterais nao contam como confirmacao. "
                "Se a resposta for positiva, agradeca e informe que a validacao foi concluida. "
                "Se a resposta for negativa, agradeca e diga que o cadastro sera atualizado. "
                "Se a resposta estiver confusa, faca no maximo uma repergunta curta. "
                "Use frases curtas, ritmo natural e linguagem apropriada para telefone."
            )
        profile_instructions = self._resolve_style_profile_instructions(context)
        if profile_instructions:
            instructions = f"{instructions} {profile_instructions}"
        if context.resolved_style_instructions:
            instructions = f"{instructions} {context.resolved_style_instructions.strip()}"
        if self.style_instructions and self.style_instructions.strip() != (context.resolved_style_instructions or "").strip():
            instructions = f"{instructions} {self.style_instructions.strip()}"
        return instructions

    def _build_initial_turn_prompt(self, context: RealtimeCallContext) -> str:
        caller_company_name = context.caller_company_name or "Central de Validacao Cadastral"
        if context.workflow_kind == "supplier_validation":
            segment_name = context.segment_name or "o segmento informado"
            return (
                "Inicie agora a ligacao em portugues do Brasil. "
                "Na sua primeira fala, diga apenas um cumprimento curto e pergunte se esta tudo bem. "
                "Nao se apresente, nao explique o motivo e nao responda voce mesma ao cumprimento nessa primeira fala. "
                "Aguarde a resposta. "
                "Se a pessoa responder apenas ao cumprimento, responda brevemente e siga para a apresentacao; nao conclua nada ainda. "
                f"So depois se identifique apenas em nome da empresa {caller_company_name}, sem dizer nome proprio, "
                f"explique que esta validando fornecedores do segmento {segment_name}. "
                f"Faca somente a primeira pergunta: se esse contato pertence a empresa {context.client_name}. "
                "Aguarde a resposta. Se a resposta for negativa, agradeca e encerre; nao avance. "
                f"Faca somente a segunda pergunta depois: se a empresa fornece {segment_name}. "
                "Aguarde a resposta. Se a resposta for negativa, agradeca e encerre; nao avance. "
                "Faca somente a terceira pergunta depois: se pode receber retorno comercial por esse contato. "
                "Aguarde a resposta. Se a resposta for negativa, agradeca e encerre."
            )
        return (
            "Inicie agora a ligacao em portugues do Brasil. "
            "Primeiro cumprimente de forma natural e pergunte se esta tudo bem. "
            "Na primeira fala, nao se apresente, nao explique o motivo da ligacao e nao responda voce mesma ao cumprimento. "
            "Aguarde a resposta do cliente. "
            "Se a pessoa responder apenas ao cumprimento, responda brevemente e siga para a apresentacao; nao conclua nada nessa etapa. "
            f"So depois se identifique apenas em nome da empresa {caller_company_name}, sem dizer nome proprio, "
            f"e faca somente a pergunta se esse contato pertence a empresa {context.client_name}. "
            "Aguarde a resposta do cliente antes de continuar."
        )

    def _hydrate_context_from_batch(self, context: RealtimeCallContext) -> None:
        if self.batch_repository is None or not context.batch_id:
            return

        batch_model = self.batch_repository.get_batch_model(context.batch_id)
        if batch_model is None:
            return

        platform_account = getattr(batch_model, "platform_account", None)
        openai_credential = getattr(platform_account, "openai_credential", None) if platform_account is not None else None

        if not context.caller_company_name:
            context.caller_company_name = (
                getattr(batch_model, "caller_company_name", None)
                or getattr(platform_account, "spoken_company_name", None)
                or getattr(platform_account, "company_name", None)
            )

        if not context.workflow_kind:
            context.workflow_kind = getattr(batch_model, "workflow_kind", None) or "cadastral_validation"
        if not context.segment_name:
            context.segment_name = getattr(batch_model, "segment_name", None)
        if not context.callback_phone:
            context.callback_phone = getattr(batch_model, "callback_phone", None)
        if not context.callback_contact_name:
            context.callback_contact_name = getattr(batch_model, "callback_contact_name", None)

        if openai_credential is None:
            return

        context.resolved_api_key = (
            decrypt_provider_secret(getattr(openai_credential, "api_key", None)) or None
        )
        context.resolved_model = getattr(openai_credential, "realtime_model", None) or None
        context.resolved_voice = getattr(openai_credential, "realtime_voice", None) or None
        context.resolved_output_speed = getattr(openai_credential, "realtime_output_speed", None)
        context.resolved_style_instructions = getattr(openai_credential, "realtime_style_instructions", None) or None

    def _resolve_api_key(self, context: RealtimeCallContext | None) -> str | None:
        if context and context.resolved_api_key:
            return context.resolved_api_key
        return self.api_key

    def _resolve_model(self, context: RealtimeCallContext | None) -> str:
        if context and context.realtime_model_override:
            return context.realtime_model_override
        if context and context.resolved_model:
            return context.resolved_model
        return self.model

    def _resolve_voice(self, context: RealtimeCallContext | None) -> str:
        if context and context.realtime_voice_override:
            return context.realtime_voice_override
        if context and context.resolved_voice:
            return context.resolved_voice
        return self.voice

    def _resolve_output_speed(self, context: RealtimeCallContext | None) -> float | None:
        if context and context.realtime_output_speed_override is not None:
            return context.realtime_output_speed_override
        if context and context.resolved_output_speed is not None:
            return context.resolved_output_speed
        return self.output_speed

    def _resolve_style_profile_instructions(self, context: RealtimeCallContext | None) -> str | None:
        if context is None or not context.realtime_style_profile:
            return None

        profile_instructions = {
            "warm_feminine": (
                "Use voz feminina suave, acolhedora e natural, com leve sorriso na voz, pausas curtas e ritmo telefonico calmo."
            ),
            "clear_professional": (
                "Use tom profissional, claro e confiante, com diccao muito limpa, objetividade e sem soar fria."
            ),
            "calm_slow": (
                "Fale um pouco mais devagar, com pausas discretas, serenidade e escuta ativa, sem soar arrastada."
            ),
            "bright_friendly": (
                "Use tom amigavel e mais vivo, com energia leve, simpatia natural e fala humana sem exagero teatral."
            ),
        }
        return profile_instructions.get(context.realtime_style_profile)

    def _parse_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text_value = str(value).strip()
        return text_value or None

    def _parse_optional_float(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    def _classify_transcript(
        self,
        transcript: str,
        context: RealtimeCallContext | None = None,
        *,
        state: _BridgeState | None = None,
    ) -> CallResult | None:
        if context is not None and context.workflow_kind == "supplier_validation":
            return self._classify_supplier_transcript(transcript, state=state)

        normalized = self._normalize_text(transcript)
        neutral_non_answer_signals = [
            "quem fala",
            "quem esta falando",
            "quem esta ligando",
            "de onde voce fala",
            "por que",
            "pode explicar",
            "nao entendi",
            "pode repetir",
        ]
        social_non_answer_signals = [
            "estou bem",
            "to bem",
            "tudo bem",
            "tudo certo",
            "bom dia",
            "boa tarde",
            "boa noite",
            "oi",
            "ola",
            "alo",
            "e voce",
            "e vc",
        ]
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
            "correto",
            "esta correto",
            "ta correto",
            "certeza",
            "com certeza",
            "pertence",
            "e da empresa",
            "continua sendo",
            "isso mesmo",
        ]

        if self._contains_any_signal(normalized, neutral_non_answer_signals):
            return None

        if self._contains_any_signal(normalized, social_non_answer_signals):
            tokens = normalized.split()
            if len(tokens) <= 4:
                return None

        if self._contains_any_signal(normalized, negative_signals):
            return CallResult.REJECTED

        if self._contains_any_signal(normalized, positive_signals):
            return CallResult.CONFIRMED

        if self._is_contextual_cadastral_affirmative(transcript, state=state):
            return CallResult.CONFIRMED

        return None

    def _is_contextual_cadastral_affirmative(
        self,
        transcript: str,
        *,
        state: _BridgeState | None = None,
    ) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False

        if state is None or not state.pending_cadastral_confirmation_question:
            return False

        contextual_affirmatives = {
            "perfeito",
            "perfeitissimo",
            "perfeitissima",
            "combinado",
            "fechado",
        }
        return normalized in contextual_affirmatives

    def _is_substantive_cadastral_confirmation_reply(self, transcript: str) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False

        neutral_non_answer_signals = [
            "quem fala",
            "quem esta falando",
            "quem esta ligando",
            "de onde voce fala",
            "por que",
            "pode explicar",
            "nao entendi",
            "pode repetir",
        ]
        social_non_answer_signals = [
            "estou bem",
            "to bem",
            "tudo bem",
            "tudo certo",
            "bom dia",
            "boa tarde",
            "boa noite",
            "oi",
            "ola",
            "alo",
            "e voce",
            "e vc",
        ]

        if self._contains_any_signal(normalized, neutral_non_answer_signals):
            return False
        if normalized in social_non_answer_signals:
            return False
        return True

    def _capture_cadastral_question_state(self, transcript: str, state: _BridgeState) -> None:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return

        contact_reference_signals = ["numero", "telefone", "contato", "celular", "linha"]
        phone_question_signals = [
            "pertence a empresa",
            "esse contato pertence",
            "esse telefone pertence",
            "esse numero pertence",
            "e da empresa",
        ]

        if any(signal in normalized for signal in contact_reference_signals) and self._contains_any_signal(
            normalized,
            phone_question_signals,
        ):
            state.pending_cadastral_confirmation_question = True
            state.cadastral_confirmation_response_received = False
            return

        if self._contains_any_signal(
            normalized,
            [
                "validacao concluida",
                "cadastro sera atualizado",
                "contato confirmado",
                "numero confirmado",
                "obrigado pela confirmacao",
                "obrigada pela confirmacao",
            ],
        ):
            state.pending_cadastral_confirmation_question = False

    def _assistant_supplier_question_slot(self, transcript: str) -> str | None:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return None

        contact_reference_signals = ["numero", "telefone", "contato", "celular", "linha"]
        phone_question_signals = [
            "pertence a empresa",
            "esse contato pertence",
            "esse telefone pertence",
            "esse numero pertence",
            "e da empresa",
        ]
        supplies_question_signals = [
            "fornece",
            "fornecem",
            "trabalha com",
            "trabalham com",
            "vende",
            "vendem",
            "atua com",
            "atuam com",
        ]
        callback_question_signals = [
            "retorno comercial",
            "retorno do comercial",
            "retorno do time comercial",
            "entrar em contato",
            "ligar",
            "pode receber retorno comercial",
            "pode receber contato comercial",
            "posso registrar esse telefone",
            "posso registrar esse contato",
        ]

        if any(signal in normalized for signal in contact_reference_signals) and self._contains_any_signal(normalized, phone_question_signals):
            return "phone_belongs"
        if self._contains_any_signal(normalized, supplies_question_signals):
            return "supplies_segment"
        if self._contains_any_signal(normalized, callback_question_signals):
            return "commercial_interest"
        return None

    def _capture_supplier_question_state(self, transcript: str, state: _BridgeState) -> None:
        slot = self._assistant_supplier_question_slot(transcript)
        if slot is None:
            return
        state.pending_supplier_question = slot
        logger.info(
            "Pergunta ativa de qualificacao de fornecedor registrada | batch_id=%s external_id=%s pending_supplier_question=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            slot,
        )

    def _mark_supplier_confirmation(self, state: _BridgeState, slot: str) -> None:
        if slot == "phone_belongs":
            state.supplier_phone_belongs_confirmed = True
        elif slot == "supplies_segment":
            state.supplier_supplies_segment_confirmed = True
        elif slot == "commercial_interest":
            state.supplier_callback_accept_confirmed = True

    def _supplier_confirmation_complete(self, state: _BridgeState) -> bool:
        return (
            state.supplier_phone_belongs_confirmed
            and state.supplier_supplies_segment_confirmed
            and state.supplier_callback_accept_confirmed
        )

    def _is_simple_affirmative(self, normalized: str) -> bool:
        simple_affirmatives = {
            "sim",
            "isso",
            "isso mesmo",
            "correto",
            "claro",
            "com certeza",
            "sem problema",
            "pode",
            "pode sim",
        }
        return (
            normalized in simple_affirmatives
            or normalized.startswith("sim ")
            or normalized.startswith("claro ")
            or normalized.startswith("pode ")
        )

    def _is_simple_negative(self, normalized: str) -> bool:
        return normalized == "nao" or normalized.startswith("nao ") or normalized == "negativo"

    def _classify_supplier_transcript(
        self,
        transcript: str,
        *,
        state: _BridgeState | None = None,
    ) -> CallResult | None:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return None

        wrong_company_signals = [
            "numero errado",
            "nao pertence",
            "nao e da empresa",
            "nao trabalho nessa empresa",
            "nao conheco essa empresa",
        ]
        no_supply_signals = [
            "nao trabalhamos com",
            "nao fornecemos",
            "nao vendemos",
            "nao atuamos com",
        ]
        no_interest_signals = [
            "nao temos interesse",
            "sem interesse",
            "nao podem entrar em contato",
            "nao queremos contato",
        ]
        neutral_non_answer_signals = [
            "quem fala",
            "de onde voce fala",
            "pode explicar",
            "nao entendi",
            "pode repetir",
        ]
        social_non_answer_signals = [
            "estou bem",
            "to bem",
            "tudo bem",
            "tudo certo",
            "bom dia",
            "boa tarde",
            "boa noite",
            "oi",
            "ola",
            "alo",
            "e voce",
            "e vc",
            "pode falar",
        ]
        belongs_signals = [
            "e da empresa",
            "esse numero pertence",
            "esse contato pertence",
            "esse telefone pertence",
            "sim pertence",
            "sim pertencem",
            "pertence a empresa",
            "pertence",
            "pertencem",
        ]
        supplies_signals = [
            "trabalhamos com",
            "fornecemos",
            "vendemos",
            "sim fornecemos",
            "sim trabalhamos",
        ]
        callback_signals = [
            "pode falar com o comercial",
            "podem entrar em contato",
            "pode entrar em contato",
            "podem ligar",
            "pode ligar",
        ]

        if self._contains_any_signal(normalized, wrong_company_signals):
            if state is not None:
                state.supplier_rejection_reason = "phone_belongs"
                state.pending_supplier_question = None
            return CallResult.REJECTED
        if self._contains_any_signal(normalized, no_supply_signals):
            if state is not None:
                state.supplier_rejection_reason = "supplies_segment"
                state.pending_supplier_question = None
            return CallResult.REJECTED
        if self._contains_any_signal(normalized, no_interest_signals):
            if state is not None:
                state.supplier_rejection_reason = "commercial_interest"
                state.pending_supplier_question = None
            return CallResult.REJECTED

        belongs_match = self._contains_any_signal(normalized, belongs_signals)
        supplies_match = self._contains_any_signal(normalized, supplies_signals)
        callback_match = self._contains_any_signal(normalized, callback_signals)

        if state is not None:
            pending_supplier_question = state.pending_supplier_question
            if pending_supplier_question and self._is_simple_negative(normalized):
                state.supplier_rejection_reason = pending_supplier_question
                state.pending_supplier_question = None
                return CallResult.REJECTED

            explicit_slots: set[str] = set()
            if belongs_match:
                explicit_slots.add("phone_belongs")
                self._mark_supplier_confirmation(state, "phone_belongs")
            if supplies_match:
                explicit_slots.add("supplies_segment")
                self._mark_supplier_confirmation(state, "supplies_segment")
            if callback_match:
                explicit_slots.add("commercial_interest")
                self._mark_supplier_confirmation(state, "commercial_interest")

            if pending_supplier_question and self._is_simple_affirmative(normalized):
                if not explicit_slots or pending_supplier_question in explicit_slots:
                    self._mark_supplier_confirmation(state, pending_supplier_question)
                    explicit_slots.add(pending_supplier_question)

            if pending_supplier_question:
                if pending_supplier_question in explicit_slots:
                    state.pending_supplier_question = None
            elif explicit_slots:
                state.pending_supplier_question = None

            if self._supplier_confirmation_complete(state):
                logger.info(
                    "Validacao de fornecedor com confirmacoes acumuladas | batch_id=%s external_id=%s phone=%s segment=%s callback=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    state.supplier_phone_belongs_confirmed,
                    state.supplier_supplies_segment_confirmed,
                    state.supplier_callback_accept_confirmed,
                )
                return CallResult.CONFIRMED

            if pending_supplier_question or belongs_match or supplies_match or callback_match:
                logger.info(
                    "Estado parcial da validacao de fornecedor apos transcript | batch_id=%s external_id=%s pending_supplier_question=%s phone=%s segment=%s callback=%s transcript=%s",
                    state.context.batch_id if state.context else None,
                    state.context.external_id if state.context else None,
                    state.pending_supplier_question,
                    state.supplier_phone_belongs_confirmed,
                    state.supplier_supplies_segment_confirmed,
                    state.supplier_callback_accept_confirmed,
                    transcript,
                )

        if self._contains_any_signal(normalized, neutral_non_answer_signals):
            return None
        if self._contains_any_signal(normalized, social_non_answer_signals):
            return None
        if normalized == "sim" or normalized.startswith("sim "):
            return None
        if normalized == "nao" or normalized.startswith("nao "):
            return CallResult.REJECTED
        return None

    def _classify_assistant_transcript(
        self,
        transcript: str,
        *,
        state: _BridgeState | None = None,
    ) -> CallResult | None:
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
            "obrigada pela confirmacao",
            "agradeco pela confirmacao",
            "agradeco a confirmacao",
            "validacao concluida",
            "contato confirmado",
            "numero confirmado",
        ]

        supplier_runtime_state = (
            state is not None
            and (
                (
                    state.context is not None
                    and state.context.workflow_kind == "supplier_validation"
                )
                or state.pending_supplier_question is not None
                or state.supplier_phone_belongs_confirmed
                or state.supplier_supplies_segment_confirmed
                or state.supplier_callback_accept_confirmed
            )
        )

        if supplier_runtime_state:
            supplier_completion_signals = [
                "retorno comercial",
                "contato comercial",
                "obrigado pela confirmacao",
                "obrigada pela confirmacao",
                "agradeco a confirmacao",
                "ate mais",
                "tenha um otimo dia",
                "bom dia para voce",
                "bom dia pra voce",
                "qualquer coisa estamos a disposicao",
                "qualquer coisa estamos por aqui",
                "agradeco a atencao",
            ]
            if (
                self._supplier_confirmation_complete(state)
                and self._contains_any_signal(normalized, supplier_completion_signals)
            ):
                return CallResult.CONFIRMED

            if self._contains_any_signal(normalized, negative_signals):
                return CallResult.REJECTED

            if (
                state is not None
                and state.context is not None
                and state.context.workflow_kind == "supplier_validation"
            ):
                return None

        if self._contains_any_signal(normalized, negative_signals):
            return CallResult.REJECTED

        if self._contains_any_signal(normalized, positive_signals):
            return CallResult.CONFIRMED

        return None

    def _assistant_transcript_signals_final_goodbye(self, transcript: str) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False

        strong_goodbye_signals = [
            "qualquer coisa estamos por aqui",
            "qualquer coisa estamos a disposicao",
            "fico a disposicao",
            "ficamos a disposicao",
            "um abraco",
            "tenha um otimo dia",
            "otimo dia pra voce",
            "bom dia pra voce",
            "bom dia para voce",
            "um bom dia",
            "boa tarde pra voce",
            "boa noite pra voce",
            "ate logo",
            "ate mais",
            "agradeco a atencao",
            "muito obrigado pela atencao",
            "muito obrigada pela atencao",
        ]
        return self._contains_any_signal(normalized, strong_goodbye_signals)

    def _should_create_response_for_user_transcript(
        self,
        transcript: str,
        *,
        state: _BridgeState | None = None,
    ) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False

        filler_tokens = {
            "a",
            "ah",
            "ahn",
            "aham",
            "eh",
            "er",
            "hm",
            "hmm",
            "hum",
            "mmm",
            "uh",
            "uhum",
            "um",
        }
        tokens = normalized.split()
        if tokens and all(token in filler_tokens for token in tokens):
            return False
        short_social_greetings = {
            "tudo bem",
            "oi tudo bem",
            "ola tudo bem",
            "bom dia",
            "boa tarde",
            "boa noite",
        }
        if normalized in short_social_greetings:
            if (
                state is not None
                and state.assistant_response_count == 1
                and state.classification is None
            ):
                return True
            return False
        return True

    def _should_accept_assistant_classification(
        self,
        classification: CallResult | None,
        *,
        state: _BridgeState,
    ) -> bool:
        if classification is None:
            return False

        if state.context is not None and state.context.workflow_kind == "supplier_validation":
            return True

        return state.classification is not None or state.cadastral_confirmation_response_received

    def _register_classification(
        self,
        classification: CallResult | None,
        *,
        source: str,
        state: _BridgeState,
    ) -> None:
        if classification is None:
            return

        if state.classification is not None:
            return

        state.classification = classification
        state.classification_source = source
        if (
            state.context is not None
            and state.context.workflow_kind == "supplier_validation"
            and classification == CallResult.REJECTED
            and source == "user"
        ):
            state.pending_response_instruction = self._build_supplier_rejection_close_prompt(state)
        target_response_count = state.assistant_response_count + 1
        if source == "user" and state.openai_response_active:
            target_response_count += 1
        state.close_after_assistant_response_count = target_response_count
        logger.info(
            "Classificacao final registrada | batch_id=%s external_id=%s classification=%s source=%s close_after_assistant_response_count=%s assistant_response_count=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            state.classification,
            state.classification_source,
            state.close_after_assistant_response_count,
            state.assistant_response_count,
        )

    def _should_terminate_provider_call(self, state: _BridgeState) -> bool:
        if state.should_close_twilio:
            return True

        if state.classification is None:
            return False

        target_response_count = state.close_after_assistant_response_count
        if target_response_count is None:
            return False

        if state.assistant_response_count < target_response_count:
            return False

        if (
            state.classification_source == "user"
            and state.last_assistant_response_classification != state.classification
            and not self._supplier_user_rejection_goodbye_can_close(state)
        ):
            return False

        return True

    def _current_loop_time(self) -> float:
        with contextlib.suppress(RuntimeError):
            return asyncio.get_running_loop().time()
        return time.monotonic()

    def _request_graceful_close_after_current_audio(
        self,
        state: _BridgeState,
        *,
        reason: str,
    ) -> None:
        if state.waiting_close_mark_name or state.should_close_twilio:
            return

        if state.latest_output_mark_name:
            state.waiting_close_mark_name = state.latest_output_mark_name
            state.close_twilio_not_before = self._current_loop_time() + 5.0
            logger.info(
                "Fechamento gracioso do Media Stream aguardando confirmacao de reproducao do Twilio | batch_id=%s external_id=%s assistant_response_count=%s classification=%s reason=%s waiting_mark=%s timeout_at=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                state.assistant_response_count,
                state.classification,
                reason,
                state.waiting_close_mark_name,
                state.close_twilio_not_before,
            )
            return

        state.should_close_twilio = True
        state.close_twilio_not_before = self._current_loop_time() + 2.5
        logger.info(
            "Fechamento gracioso do Media Stream agendado sem mark do Twilio | batch_id=%s external_id=%s assistant_response_count=%s classification=%s reason=%s close_not_before=%s",
            state.context.batch_id if state.context else None,
            state.context.external_id if state.context else None,
            state.assistant_response_count,
            state.classification,
            reason,
            state.close_twilio_not_before,
        )

    async def _maybe_close_twilio_stream(
        self,
        twilio_websocket: WebSocket,
        state: _BridgeState,
    ) -> None:
        del twilio_websocket

        if state.classification is None:
            return

        target_response_count = state.close_after_assistant_response_count
        if target_response_count is None:
            state.close_after_assistant_response_count = state.assistant_response_count + 1
            target_response_count = state.close_after_assistant_response_count

        if state.assistant_response_count < target_response_count:
            logger.info(
                "Aguardando resposta final da IA antes de encerrar a chamada | batch_id=%s external_id=%s classification=%s assistant_response_count=%s close_after_assistant_response_count=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                state.classification,
                state.assistant_response_count,
                target_response_count,
            )
            return

        if (
            state.classification_source == "user"
            and state.last_assistant_response_classification != state.classification
            and not self._supplier_user_rejection_goodbye_can_close(state)
        ):
            state.close_after_assistant_response_count = state.assistant_response_count + 1
            logger.info(
                "Mantendo chamada ativa porque a ultima resposta da IA ainda nao foi conclusiva | batch_id=%s external_id=%s classification=%s last_assistant_response_classification=%s next_close_after_assistant_response_count=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                state.classification,
                state.last_assistant_response_classification,
                state.close_after_assistant_response_count,
            )
            return

        self._request_graceful_close_after_current_audio(
            state,
            reason="classificacao final registrada",
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
        if not mark_name:
            return

        releasing_user_capture = (
            state.ignore_twilio_audio_until_mark_name == mark_name
            and state.waiting_close_mark_name != mark_name
            and not state.should_close_twilio
        )

        if releasing_user_capture:
            state.ignore_twilio_audio_until_mark_name = None
            state.ignore_twilio_audio_until = self._current_loop_time() + 0.12
            logger.info(
                "Audio final da pergunta foi reproduzido pelo Twilio; liberando nova captura do cliente | batch_id=%s external_id=%s mark_name=%s",
                state.context.batch_id if state.context else None,
                state.context.external_id if state.context else None,
                mark_name,
            )

        if state.waiting_close_mark_name != mark_name:
            return

        state.waiting_close_mark_name = None
        state.should_close_twilio = True
        state.close_twilio_not_before = self._current_loop_time()
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
        self._ensure_runtime_configured(None)

    def _ensure_runtime_configured(self, context: RealtimeCallContext | None) -> None:
        if self._resolve_api_key(context) and self._resolve_model(context) and self._resolve_voice(context):
            return
        raise ProviderConfigurationError(
            "OpenAI Realtime",
            "defina uma chave OpenAI, o modelo Realtime e a voz padrao, globalmente ou na conta vinculada ao lote.",
        )

    def _should_log_chunk(self, chunk_index: int) -> bool:
        return chunk_index <= 3 or chunk_index % 25 == 0
