from __future__ import annotations

from datetime import datetime, timezone
import logging
import unicodedata
from typing import Any
from uuid import uuid4

from ..core.memory_store import LocalTestMemoryStore
from ..schemas.test_flow import (
    ClearStateResponse,
    LocalBusinessStatus,
    LocalTechnicalStatus,
    LocalTestFlowResponse,
    LocalTestStateResponse,
    LocalValidationRequest,
    ManualWhatsAppSendRequest,
    WebhookEventSummary,
    WebhookReceiveResponse,
    WhatsAppSendResult,
)
from .call_simulator import CallSimulatorService
from .cnpj import is_valid_cnpj, normalize_cnpj
from .phone import normalize_phone
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class LocalTestFlowService:
    def __init__(
        self,
        *,
        memory_store: LocalTestMemoryStore,
        call_simulator: CallSimulatorService,
        whatsapp_service: WhatsAppService,
        verify_token: str | None,
    ) -> None:
        self.memory_store = memory_store
        self.call_simulator = call_simulator
        self.whatsapp_service = whatsapp_service
        self.verify_token = verify_token

    async def simulate_validation(
        self,
        payload: LocalValidationRequest,
    ) -> LocalTestFlowResponse:
        request_id = uuid4().hex
        created_at = self._now()
        logger.info(
            "Iniciando simulacao local de validacao | request_id=%s client_name=%s call_scenario=%s",
            request_id,
            payload.client_name,
            payload.call_scenario,
        )

        self.memory_store.add_log(
            "received",
            "Nova simulacao de validacao recebida.",
            payload.model_dump(mode="json"),
        )

        cnpj_normalized = normalize_cnpj(payload.cnpj)
        phone_normalized = normalize_phone(payload.phone)

        if not is_valid_cnpj(payload.cnpj):
            logger.warning(
                "Simulacao local encerrada por CNPJ invalido | request_id=%s cnpj=%s",
                request_id,
                payload.cnpj,
            )
            response = LocalTestFlowResponse(
                request_id=request_id,
                client_name=payload.client_name,
                cnpj_original=payload.cnpj,
                cnpj_normalized=cnpj_normalized or None,
                phone_original=payload.phone,
                phone_normalized=phone_normalized,
                call_scenario=payload.call_scenario,
                should_send_whatsapp=False,
                fallback_message=payload.fallback_message,
                technical_status=LocalTechnicalStatus.ERROR,
                business_status=None,
                flow_finished=True,
                observation="CNPJ invalido para testes locais.",
                created_at=created_at,
                updated_at=created_at,
            )
            self._store_response(response)
            self.memory_store.add_log(
                "error",
                "Simulacao encerrada por CNPJ invalido.",
                {"request_id": request_id, "cnpj": payload.cnpj},
            )
            return response

        if phone_normalized is None:
            logger.warning(
                "Simulacao local encerrada por telefone invalido | request_id=%s phone=%s",
                request_id,
                payload.phone,
            )
            response = LocalTestFlowResponse(
                request_id=request_id,
                client_name=payload.client_name,
                cnpj_original=payload.cnpj,
                cnpj_normalized=cnpj_normalized,
                phone_original=payload.phone,
                phone_normalized=None,
                call_scenario=payload.call_scenario,
                should_send_whatsapp=False,
                fallback_message=payload.fallback_message,
                technical_status=LocalTechnicalStatus.ERROR,
                business_status=None,
                flow_finished=True,
                observation="Telefone invalido para testes locais.",
                created_at=created_at,
                updated_at=created_at,
            )
            self._store_response(response)
            self.memory_store.add_log(
                "error",
                "Simulacao encerrada por telefone invalido.",
                {"request_id": request_id, "phone": payload.phone},
            )
            return response

        logger.info(
            "Dados normalizados na simulacao local | request_id=%s cnpj_normalized=%s phone_normalized=%s",
            request_id,
            cnpj_normalized,
            phone_normalized,
        )
        self.memory_store.add_log(
            "normalized",
            "Dados normalizados para simulacao local.",
            {
                "request_id": request_id,
                "cnpj_normalized": cnpj_normalized,
                "phone_normalized": phone_normalized,
            },
        )

        call_result = self.call_simulator.simulate(payload.call_scenario)
        logger.info(
            "Resultado da ligacao simulada | request_id=%s call_status=%s call_result=%s should_send_whatsapp=%s",
            request_id,
            call_result.call_status,
            call_result.call_result,
            call_result.should_send_whatsapp,
        )
        self.memory_store.add_log(
            "call_simulated",
            "Resultado de ligacao simulada gerado.",
            {
                "request_id": request_id,
                "call_status": call_result.call_status.value,
                "call_result": call_result.call_result.value,
                "should_send_whatsapp": call_result.should_send_whatsapp,
            },
        )

        if not call_result.should_send_whatsapp:
            logger.info(
                "Simulacao local concluida sem fallback WhatsApp | request_id=%s",
                request_id,
            )
            response = LocalTestFlowResponse(
                request_id=request_id,
                client_name=payload.client_name,
                cnpj_original=payload.cnpj,
                cnpj_normalized=cnpj_normalized,
                phone_original=payload.phone,
                phone_normalized=phone_normalized,
                call_scenario=payload.call_scenario,
                call_status=call_result.call_status,
                call_result=call_result.call_result,
                call_business_status=call_result.business_status,
                should_send_whatsapp=False,
                fallback_message=payload.fallback_message,
                technical_status=LocalTechnicalStatus.COMPLETED,
                business_status=LocalBusinessStatus.CONFIRMED_BY_CALL,
                flow_finished=True,
                observation="Ligacao confirmada. Fallback via WhatsApp nao foi necessario.",
                created_at=created_at,
                updated_at=created_at,
            )
            self._store_response(response)
            return response

        logger.info(
            "Simulacao local vai acionar fallback WhatsApp | request_id=%s phone=%s",
            request_id,
            phone_normalized,
        )
        whatsapp_result = await self.whatsapp_service.send_text_message(
            phone_normalized,
            payload.fallback_message,
        )

        response = LocalTestFlowResponse(
            request_id=request_id,
            client_name=payload.client_name,
            cnpj_original=payload.cnpj,
            cnpj_normalized=cnpj_normalized,
            phone_original=payload.phone,
            phone_normalized=phone_normalized,
            call_scenario=payload.call_scenario,
            call_status=call_result.call_status,
            call_result=call_result.call_result,
            call_business_status=call_result.business_status,
            should_send_whatsapp=True,
            fallback_message=payload.fallback_message,
            technical_status=(
                LocalTechnicalStatus.WHATSAPP_SENT
                if whatsapp_result.success
                else LocalTechnicalStatus.ERROR
            ),
            business_status=(
                LocalBusinessStatus.WAITING_WHATSAPP_REPLY
                if whatsapp_result.success
                else call_result.business_status
            ),
            flow_finished=not whatsapp_result.success,
            whatsapp=whatsapp_result,
            meta_message_id=whatsapp_result.meta_message_id,
            observation=(
                "Mensagem de fallback enviada com sucesso. Aguardando resposta do usuario."
                if whatsapp_result.success
                else whatsapp_result.error_message
            ),
            created_at=created_at,
            updated_at=self._now(),
        )
        self._store_response(response)
        self._record_whatsapp_send(
            whatsapp_result=whatsapp_result,
            origin="test_validate",
            phone_normalized=phone_normalized,
            request_id=request_id,
            client_name=payload.client_name,
        )
        logger.info(
            "Resultado do fallback WhatsApp na simulacao local | request_id=%s success=%s meta_http_status=%s meta_message_id=%s",
            request_id,
            whatsapp_result.success,
            whatsapp_result.meta_http_status,
            whatsapp_result.meta_message_id,
        )
        self.memory_store.add_log(
            str(response.technical_status),
            "Fallback via WhatsApp processado.",
            {
                "request_id": request_id,
                "meta_http_status": whatsapp_result.meta_http_status,
                "meta_message_id": whatsapp_result.meta_message_id,
                "success": whatsapp_result.success,
                "error_message": whatsapp_result.error_message,
            },
        )
        return response

    async def send_manual_whatsapp(
        self,
        payload: ManualWhatsAppSendRequest,
    ) -> WhatsAppSendResult:
        phone_normalized = normalize_phone(payload.phone)
        phone_for_send = phone_normalized or payload.phone
        logger.info("Enviando WhatsApp manual no laboratorio local | phone=%s", phone_for_send)
        whatsapp_result = await self.whatsapp_service.send_text_message(
            phone_for_send,
            payload.message,
        )
        self._record_whatsapp_send(
            whatsapp_result=whatsapp_result,
            origin="manual_send",
            phone_normalized=phone_for_send,
            request_id=None,
            client_name=None,
        )
        self.memory_store.add_log(
            "whatsapp_sent" if whatsapp_result.success else "error",
            "Envio manual de WhatsApp executado.",
            {
                "phone": phone_for_send,
                "meta_http_status": whatsapp_result.meta_http_status,
                "meta_message_id": whatsapp_result.meta_message_id,
                "success": whatsapp_result.success,
                "error_message": whatsapp_result.error_message,
            },
        )
        return whatsapp_result

    def get_state(self) -> LocalTestStateResponse:
        return LocalTestStateResponse.model_validate(self.memory_store.get_state())

    def clear_state(self) -> ClearStateResponse:
        logger.info("Limpando estado do laboratorio local")
        self.memory_store.reset()
        return ClearStateResponse(message="Estado local de testes limpo com sucesso.")

    def verify_webhook(
        self,
        mode: str | None,
        verify_token: str | None,
        challenge: str | None,
    ) -> bool:
        is_valid = (
            mode == "subscribe"
            and verify_token is not None
            and challenge is not None
            and self.verify_token is not None
            and verify_token == self.verify_token
        )
        logger.info(
            "Validacao de webhook da Meta executada | mode=%s verify_token_present=%s is_valid=%s",
            mode,
            verify_token is not None,
            is_valid,
        )
        return is_valid

    def process_webhook_payload(
        self,
        payload: dict[str, Any],
    ) -> WebhookReceiveResponse:
        events = self._extract_webhook_events(payload)
        last_event_summary: dict[str, Any] | None = None
        logger.info("Processando webhook da Meta | events_detected=%s", len(events))

        for event in events:
            event_summary = event.model_dump(mode="json")
            last_event_summary = event_summary
            logger.info(
                "Evento da Meta extraido | event_type=%s phone=%s message_id=%s status=%s",
                event.event_type,
                event.phone,
                event.message_id,
                event.status,
            )
            self.memory_store.add_log(
                "webhook_received",
                "Webhook da Meta recebido.",
                event_summary,
            )

            if event.event_type == "message" and event.text:
                self._handle_incoming_message(event)

            if event.event_type == "status" and event.message_id and event.status:
                updated_request = self.memory_store.update_request_by_message_id(
                    event.message_id,
                    {
                        "technical_status": LocalTechnicalStatus.WEBHOOK_RECEIVED.value,
                        "last_delivery_status": event.status,
                        "updated_at": self._now(),
                    },
                )
                if updated_request is not None:
                    logger.info(
                        "Status de entrega associado a simulacao local | request_id=%s status=%s message_id=%s",
                        updated_request["request_id"],
                        event.status,
                        event.message_id,
                    )
                    self.memory_store.add_log(
                        "webhook_received",
                        "Status de entrega associado a uma simulacao local.",
                        {
                            "request_id": updated_request["request_id"],
                            "status": event.status,
                            "message_id": event.message_id,
                        },
                    )

        self.memory_store.set_last_webhook(payload, last_event_summary)
        return WebhookReceiveResponse(received=True, events_processed=len(events))

    def _handle_incoming_message(self, event: WebhookEventSummary) -> None:
        if event.phone is None or event.text is None:
            logger.warning("Mensagem do webhook ignorada por falta de phone/text")
            return

        normalized_reply = _normalize_reply_text(event.text)
        logger.info(
            "Interpretando resposta recebida via WhatsApp | phone=%s normalized_reply=%s",
            event.phone,
            normalized_reply,
        )
        if normalized_reply.startswith("SIM"):
            business_status = LocalBusinessStatus.CONFIRMED_BY_WHATSAPP
        elif normalized_reply.startswith("NAO"):
            business_status = LocalBusinessStatus.REJECTED_BY_WHATSAPP
        else:
            logger.info(
                "Resposta recebida sem classificacao SIM/NAO | phone=%s text=%s",
                event.phone,
                event.text,
            )
            self.memory_store.add_log(
                "webhook_received",
                "Mensagem recebida sem resposta reconhecida para SIM/NAO.",
                {"phone": event.phone, "text": event.text},
            )
            return

        updated_request = self.memory_store.update_request_by_phone(
            event.phone,
            {
                "technical_status": LocalTechnicalStatus.COMPLETED.value,
                "business_status": business_status.value,
                "flow_finished": True,
                "last_user_reply": event.text,
                "updated_at": self._now(),
                "observation": "Resposta recebida via webhook da Meta.",
            },
            only_waiting_whatsapp=True,
        )

        if updated_request is None:
            logger.warning(
                "Resposta via WhatsApp sem fluxo pendente correspondente | phone=%s text=%s",
                event.phone,
                event.text,
            )
            self.memory_store.add_log(
                "webhook_received",
                "Mensagem recebida, mas nenhum fluxo pendente foi localizado.",
                {"phone": event.phone, "text": event.text},
            )
            return

        logger.info(
            "Fluxo local concluido via WhatsApp | request_id=%s business_status=%s",
            updated_request["request_id"],
            business_status.value,
        )
        self.memory_store.add_log(
            "completed",
            "Fluxo concluido com resposta recebida via WhatsApp.",
            {
                "request_id": updated_request["request_id"],
                "business_status": business_status.value,
                "reply": event.text,
            },
        )

    def _record_whatsapp_send(
        self,
        *,
        whatsapp_result: WhatsAppSendResult,
        origin: str,
        phone_normalized: str,
        request_id: str | None,
        client_name: str | None,
    ) -> None:
        logger.info(
            "Registrando historico local de envio WhatsApp | origin=%s phone=%s request_id=%s success=%s",
            origin,
            phone_normalized,
            request_id,
            whatsapp_result.success,
        )
        send_record = whatsapp_result.model_dump(mode="json")
        send_record.update(
            {
                "origin": origin,
                "phone_normalized": phone_normalized,
                "request_id": request_id,
                "client_name": client_name,
                "created_at": self._now(),
            }
        )
        self.memory_store.record_whatsapp_send(send_record)

    def _store_response(self, response: LocalTestFlowResponse) -> None:
        logger.info(
            "Persistindo resultado local em memoria | request_id=%s technical_status=%s business_status=%s",
            response.request_id,
            response.technical_status,
            response.business_status,
        )
        self.memory_store.upsert_test_request(response.model_dump(mode="json"))

    def _extract_webhook_events(
        self,
        payload: dict[str, Any],
    ) -> list[WebhookEventSummary]:
        extracted_events: list[WebhookEventSummary] = []

        for entry in payload.get("entry", []):
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []):
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue

                for message in value.get("messages", []):
                    if not isinstance(message, dict):
                        continue
                    phone = message.get("from")
                    text = None
                    text_payload = message.get("text")
                    if isinstance(text_payload, dict):
                        body = text_payload.get("body")
                        if isinstance(body, str):
                            text = body
                    phone_normalized = normalize_phone(str(phone)) if phone is not None else None
                    extracted_events.append(
                        WebhookEventSummary(
                            event_type="message",
                            phone=phone_normalized,
                            message_id=message.get("id"),
                            text=text,
                            raw=message,
                        )
                    )

                for status in value.get("statuses", []):
                    if not isinstance(status, dict):
                        continue
                    recipient_id = status.get("recipient_id")
                    phone_normalized = (
                        normalize_phone(str(recipient_id))
                        if recipient_id is not None
                        else None
                    )
                    extracted_events.append(
                        WebhookEventSummary(
                            event_type="status",
                            phone=phone_normalized,
                            message_id=status.get("id"),
                            status=status.get("status"),
                            raw=status,
                        )
                    )

        return extracted_events

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)


def _normalize_reply_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().upper()
