from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from ..db.models import CallAttemptModel, ValidationRecordModel, WhatsAppMessageModel
from ..domain.statuses import (
    BusinessStatus,
    CallPhoneSource,
    CallResult,
    CallStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.async_events import CallEventRequest, WhatsAppEventRequest
from ..schemas.response import ValidationBatchResponse, ValidationRecordResponse
from .errors import BatchNotFoundError, ProviderRequestError, RecordNotFoundError
from .official_company_registry_service import OfficialCompanyRegistryService
from .phone import normalize_phone
from .twilio_voice_service import TwilioVoiceService

logger = logging.getLogger(__name__)


class ValidationAsyncService:
    def __init__(
        self,
        *,
        batch_repository: ValidationBatchRepository,
        official_company_registry: OfficialCompanyRegistryService,
        twilio_voice_service: TwilioVoiceService,
    ) -> None:
        self.batch_repository = batch_repository
        self.official_company_registry = official_company_registry
        self.twilio_voice_service = twilio_voice_service

    def dispatch_batch(self, batch_id: str, *, twiml_mode: str = "media_stream") -> ValidationBatchResponse:
        logger.info("Iniciando dispatch do lote | batch_id=%s twiml_mode=%s", batch_id, twiml_mode)
        batch_model = self.batch_repository.get_batch_model(batch_id)
        if batch_model is None:
            logger.warning("Dispatch falhou, lote nao encontrado | batch_id=%s", batch_id)
            raise BatchNotFoundError(batch_id)

        for record in batch_model.records:
            logger.info(
                "Avaliando registro para dispatch | batch_id=%s external_id=%s ready_for_contact=%s final_status=%s",
                batch_id,
                record.external_id,
                record.ready_for_contact,
                record.final_status,
            )
            if not record.ready_for_contact or record.final_status != FinalStatus.PROCESSING:
                continue

            pending_attempt = self._find_pending_call_attempt(record)
            if pending_attempt is None:
                pending_attempt = self._queue_call_attempt(
                    record_model=record,
                    phone_to_dial=record.phone_normalized or record.phone_original,
                    phone_source=CallPhoneSource.PAYLOAD_PHONE,
                    business_status=BusinessStatus.READY_FOR_CALL,
                    observation="Ligacao inicial enfileirada para validacao por voz.",
                )

            self._dispatch_voice_attempt(record, pending_attempt, twiml_mode=twiml_mode)

        return self.batch_repository.save_batch(batch_model)

    def register_call_event(
        self,
        batch_id: str,
        external_id: str,
        payload: CallEventRequest,
    ) -> ValidationRecordResponse:
        logger.info(
            "Registrando evento de chamada | batch_id=%s external_id=%s provider_call_id=%s call_status=%s call_result=%s",
            batch_id,
            external_id,
            payload.provider_call_id,
            payload.call_status,
            payload.call_result,
        )
        record_model = self._get_record_model(batch_id, external_id)
        call_attempt = self._resolve_call_attempt(record_model, payload.provider_call_id)
        event_time = payload.happened_at or datetime.now(timezone.utc)

        call_attempt.provider_call_id = payload.provider_call_id or call_attempt.provider_call_id
        call_attempt.phone_dialed = (
            call_attempt.phone_dialed
            or record_model.phone_normalized
            or record_model.phone_original
        )
        call_attempt.status = payload.call_status
        call_attempt.result = payload.call_result
        call_attempt.transcript_summary = payload.transcript_summary
        call_attempt.sentiment = payload.sentiment
        call_attempt.duration_seconds = payload.duration_seconds
        call_attempt.finished_at = event_time
        call_attempt.observation = payload.observation

        record_model.call_status = payload.call_status
        record_model.call_result = payload.call_result
        record_model.transcript_summary = payload.transcript_summary
        record_model.sentiment = payload.sentiment
        record_model.phone_confirmed = False
        record_model.confirmation_source = None

        if payload.call_result == CallResult.CONFIRMED:
            logger.info(
                "Ligacao confirmada | batch_id=%s external_id=%s attempt_number=%s",
                batch_id,
                external_id,
                call_attempt.attempt_number,
            )
            record_model.technical_status = TechnicalStatus.COMPLETED
            record_model.business_status = BusinessStatus.CONFIRMED_BY_CALL
            record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
            record_model.phone_confirmed = True
            record_model.confirmation_source = (
                "voice_call_retry"
                if call_attempt.attempt_number > 1
                else "voice_call"
            )
            record_model.final_status = FinalStatus.VALIDATED
            record_model.observation = (
                payload.observation
                or "Numero confirmado por ligacao conversacional."
            )
        elif payload.call_result == CallResult.REJECTED:
            logger.info(
                "Ligacao rejeitou o numero atual | batch_id=%s external_id=%s attempt_number=%s",
                batch_id,
                external_id,
                call_attempt.attempt_number,
            )
            alternative_phone = self._lookup_alternative_phone(record_model)
            if alternative_phone is not None:
                logger.info(
                    "Telefone alternativo encontrado na base oficial | batch_id=%s external_id=%s phone=%s",
                    batch_id,
                    external_id,
                    alternative_phone,
                )
                self._queue_call_attempt(
                    record_model=record_model,
                    phone_to_dial=alternative_phone,
                    phone_source=CallPhoneSource.OFFICIAL_COMPANY_REGISTRY,
                    business_status=BusinessStatus.READY_FOR_RETRY_CALL,
                    observation=(
                        "Numero recusado na ligacao atual. Novo telefone localizado na base oficial de empresas e enfileirado para segunda tentativa."
                    ),
                )
            else:
                logger.warning(
                    "Nenhum telefone alternativo encontrado apos rejeicao | batch_id=%s external_id=%s",
                    batch_id,
                    external_id,
                )
                record_model.technical_status = TechnicalStatus.COMPLETED
                record_model.business_status = BusinessStatus.REJECTED_BY_CALL
                record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                record_model.final_status = FinalStatus.VALIDATION_FAILED
                record_model.observation = (
                    payload.observation
                    or "Numero recusado na ligacao e nenhum telefone alternativo foi encontrado na base oficial de empresas."
                )
        elif (
            payload.call_status == CallStatus.NOT_ANSWERED
            or payload.call_result == CallResult.NOT_ANSWERED
        ):
            logger.info(
                "Ligacao nao atendida, acionando fallback WhatsApp | batch_id=%s external_id=%s",
                batch_id,
                external_id,
            )
            self._ensure_whatsapp_fallback(record_model, call_attempt.phone_dialed)
            record_model.technical_status = TechnicalStatus.PROCESSING
            record_model.business_status = BusinessStatus.WAITING_WHATSAPP_REPLY
            record_model.whatsapp_status = WhatsAppStatus.WAITING_REPLY
            record_model.final_status = FinalStatus.PROCESSING
            record_model.observation = (
                payload.observation
                or "Ligacao nao atendida. Fallback por mensagem no WhatsApp foi acionado."
            )
        else:
            logger.info(
                "Ligacao inconclusiva | batch_id=%s external_id=%s",
                batch_id,
                external_id,
            )
            record_model.technical_status = TechnicalStatus.PROCESSING
            record_model.business_status = BusinessStatus.INCONCLUSIVE_CALL
            record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
            record_model.final_status = FinalStatus.PROCESSING
            record_model.observation = (
                payload.observation
                or "Ligacao inconclusiva. Fluxo aguardando tratativa adicional antes do encerramento."
            )

        return self.batch_repository.save_record(record_model)

    def register_twilio_status_callback(
        self,
        *,
        batch_id: str,
        external_id: str,
        provider_call_id: str | None,
        provider_status: str,
        duration_seconds: int | None,
    ) -> ValidationRecordResponse:
        normalized_status = provider_status.strip().lower()
        logger.info(
            "Recebido status callback do Twilio | batch_id=%s external_id=%s provider_call_id=%s provider_status=%s",
            batch_id,
            external_id,
            provider_call_id,
            normalized_status,
        )
        record_model = self._get_record_model(batch_id, external_id)
        call_attempt = self._resolve_call_attempt(record_model, provider_call_id)
        event_time = datetime.now(timezone.utc)

        call_attempt.provider_call_id = provider_call_id or call_attempt.provider_call_id
        call_attempt.duration_seconds = duration_seconds

        if normalized_status in {"initiated", "queued", "ringing"}:
            call_attempt.status = CallStatus.QUEUED
            call_attempt.observation = f"Twilio reportou o status '{normalized_status}'."
            record_model.call_status = CallStatus.QUEUED
            record_model.observation = call_attempt.observation
            return self.batch_repository.save_record(record_model)

        if normalized_status in {"answered", "in-progress"}:
            call_attempt.status = CallStatus.ANSWERED
            call_attempt.started_at = call_attempt.started_at or event_time
            call_attempt.observation = "Twilio informou que a ligacao foi atendida."
            record_model.call_status = CallStatus.ANSWERED
            record_model.business_status = BusinessStatus.CALL_ANSWERED
            record_model.technical_status = TechnicalStatus.PROCESSING
            record_model.observation = call_attempt.observation
            return self.batch_repository.save_record(record_model)

        if normalized_status == "no-answer":
            return self.register_call_event(
                batch_id,
                external_id,
                CallEventRequest(
                    provider_call_id=provider_call_id,
                    call_status=CallStatus.NOT_ANSWERED,
                    call_result=CallResult.NOT_ANSWERED,
                    duration_seconds=duration_seconds,
                    observation="Twilio informou que a ligacao nao foi atendida.",
                ),
            )

        if normalized_status in {"busy", "failed", "canceled"}:
            return self.register_call_event(
                batch_id,
                external_id,
                CallEventRequest(
                    provider_call_id=provider_call_id,
                    call_status=CallStatus.FAILED,
                    call_result=CallResult.INCONCLUSIVE,
                    duration_seconds=duration_seconds,
                    observation=f"Twilio encerrou a ligacao com o status '{normalized_status}'.",
                ),
            )

        if normalized_status == "completed":
            call_attempt.finished_at = event_time
            if duration_seconds is not None:
                call_attempt.duration_seconds = duration_seconds

            if (
                record_model.final_status == FinalStatus.PROCESSING
                and record_model.call_status == CallStatus.ANSWERED
            ):
                logger.info(
                    "Twilio concluiu a ligacao e a API seguira aguardando o resultado final do media stream | batch_id=%s external_id=%s provider_call_id=%s",
                    batch_id,
                    external_id,
                    provider_call_id,
                )
                call_attempt.observation = (
                    "Twilio concluiu a ligacao. Aguardando classificacao final do Media Stream/OpenAI Realtime."
                )
                record_model.observation = (
                    record_model.observation
                    or "Ligacao encerrada pelo Twilio e aguardando classificacao final do Media Stream/OpenAI Realtime."
                )
                return self.batch_repository.save_record(record_model)

            call_attempt.observation = (
                "Twilio concluiu a ligacao. Nenhum evento final de media stream foi recebido para classificar a conversa."
            )
            if record_model.final_status == FinalStatus.PROCESSING:
                logger.warning(
                    "Twilio concluiu a ligacao sem classificacao final do media stream | batch_id=%s external_id=%s provider_call_id=%s",
                    batch_id,
                    external_id,
                    provider_call_id,
                )
                call_attempt.result = CallResult.INCONCLUSIVE
                record_model.call_status = CallStatus.ANSWERED
                record_model.call_result = CallResult.INCONCLUSIVE
                record_model.technical_status = TechnicalStatus.COMPLETED
                record_model.business_status = BusinessStatus.INCONCLUSIVE_CALL
                record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                record_model.phone_confirmed = False
                record_model.confirmation_source = None
                record_model.final_status = FinalStatus.VALIDATION_FAILED
                record_model.observation = (
                    "Ligacao encerrada pelo Twilio sem eventos do Media Stream/OpenAI Realtime. "
                    "Verifique os webhooks /twiml e /media-stream."
                )
            else:
                record_model.observation = (
                    record_model.observation or call_attempt.observation
                )

            return self.batch_repository.save_record(record_model)

        call_attempt.finished_at = event_time
        call_attempt.observation = f"Twilio concluiu a ligacao com o status '{normalized_status}'."
        if duration_seconds is not None:
            call_attempt.duration_seconds = duration_seconds
        record_model.observation = call_attempt.observation
        return self.batch_repository.save_record(record_model)

    def register_whatsapp_event(
        self,
        batch_id: str,
        external_id: str,
        payload: WhatsAppEventRequest,
    ) -> ValidationRecordResponse:
        logger.info(
            "Registrando evento de WhatsApp | batch_id=%s external_id=%s provider_message_id=%s status=%s direction=%s",
            batch_id,
            external_id,
            payload.provider_message_id,
            payload.status,
            payload.direction,
        )
        record_model = self._get_record_model(batch_id, external_id)
        message_model = self._resolve_whatsapp_message(
            record_model,
            payload.provider_message_id,
        )
        event_time = payload.happened_at or datetime.now(timezone.utc)

        message_model.provider_message_id = (
            payload.provider_message_id or message_model.provider_message_id
        )
        message_model.direction = payload.direction
        message_model.message_body = payload.message_body or message_model.message_body
        message_model.response_text = payload.response_text
        message_model.status = payload.status
        message_model.observation = payload.observation

        if payload.direction == "outbound":
            message_model.sent_at = event_time
        else:
            message_model.responded_at = event_time

        if payload.status == WhatsAppStatus.CONFIRMED:
            record_model.technical_status = TechnicalStatus.COMPLETED
            record_model.business_status = BusinessStatus.CONFIRMED_BY_WHATSAPP
            record_model.whatsapp_status = WhatsAppStatus.CONFIRMED
            record_model.phone_confirmed = True
            record_model.confirmation_source = "whatsapp"
            record_model.final_status = FinalStatus.VALIDATED
            record_model.observation = payload.observation or "Numero confirmado por WhatsApp."
        elif payload.status == WhatsAppStatus.REJECTED:
            record_model.technical_status = TechnicalStatus.COMPLETED
            record_model.business_status = BusinessStatus.REJECTED_BY_WHATSAPP
            record_model.whatsapp_status = WhatsAppStatus.REJECTED
            record_model.phone_confirmed = False
            record_model.confirmation_source = "whatsapp"
            record_model.final_status = FinalStatus.VALIDATION_FAILED
            record_model.observation = payload.observation or "Numero rejeitado por WhatsApp."
        elif payload.status == WhatsAppStatus.EXPIRED:
            record_model.technical_status = TechnicalStatus.COMPLETED
            record_model.business_status = BusinessStatus.VALIDATION_FAILED
            record_model.whatsapp_status = WhatsAppStatus.EXPIRED
            record_model.phone_confirmed = False
            record_model.confirmation_source = None
            record_model.final_status = FinalStatus.VALIDATION_FAILED
            record_model.observation = (
                payload.observation or "Fallback por WhatsApp expirou sem resposta."
            )
        else:
            record_model.technical_status = TechnicalStatus.PROCESSING
            record_model.business_status = BusinessStatus.WAITING_WHATSAPP_REPLY
            record_model.whatsapp_status = payload.status
            record_model.phone_confirmed = False
            record_model.confirmation_source = None
            record_model.final_status = FinalStatus.PROCESSING
            record_model.observation = payload.observation or "Aguardando retorno do WhatsApp."

        return self.batch_repository.save_record(record_model)

    def _dispatch_voice_attempt(
        self,
        record_model: ValidationRecordModel,
        call_attempt: CallAttemptModel,
        *,
        twiml_mode: str = "media_stream",
    ) -> None:
        if not self.twilio_voice_service.is_configured():
            logger.info(
                "Provedor de voz nao configurado, mantendo tentativa em modo manual | batch_id=%s external_id=%s attempt_number=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                call_attempt.attempt_number,
            )
            return

        if not self._is_placeholder_call_id(call_attempt.provider_call_id):
            logger.info(
                "Tentativa ja possui provider_call_id real, nao sera reenviada | batch_id=%s external_id=%s provider_call_id=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                call_attempt.provider_call_id,
            )
            return

        logger.info(
            "Enviando tentativa ao provedor de voz | batch_id=%s external_id=%s attempt_number=%s phone=%s twiml_mode=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            call_attempt.attempt_number,
            call_attempt.phone_dialed or record_model.phone_original,
            twiml_mode,
        )
        try:
            dispatch_result = self.twilio_voice_service.create_outbound_call(
                batch_id=record_model.batch.batch_id,
                external_id=record_model.external_id,
                attempt_number=call_attempt.attempt_number,
                client_name=record_model.client_name,
                cnpj=record_model.cnpj_normalized or record_model.cnpj_original,
                phone_to_dial=call_attempt.phone_dialed or record_model.phone_original,
                twiml_mode=twiml_mode,
            )
        except ProviderRequestError as error:
            logger.exception(
                "Falha ao enviar chamada ao provedor de voz | batch_id=%s external_id=%s error=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                error,
            )
            call_attempt.observation = (
                f"{call_attempt.observation} Provedor de voz retornou erro temporario: {error}"
            )
            record_model.observation = call_attempt.observation
            return

        call_attempt.provider_call_id = dispatch_result.provider_call_id
        logger.info(
            "Tentativa enviada ao provedor de voz | batch_id=%s external_id=%s provider_call_id=%s provider_status=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            dispatch_result.provider_call_id,
            dispatch_result.provider_status,
        )
        call_attempt.observation = (
            "Ligacao enviada ao provedor de voz e aguardando eventos reais da chamada."
        )
        record_model.observation = call_attempt.observation

    def _find_pending_call_attempt(
        self,
        record_model: ValidationRecordModel,
    ) -> CallAttemptModel | None:
        if not record_model.call_attempts:
            return None

        last_attempt = record_model.call_attempts[-1]
        if (
            last_attempt.status == CallStatus.QUEUED
            and last_attempt.result == CallResult.PENDING_DISPATCH
        ):
            return last_attempt
        return None

    def _get_record_model(
        self, batch_id: str, external_id: str
    ) -> ValidationRecordModel:
        record_model = self.batch_repository.get_record_model(batch_id, external_id)
        if record_model is None:
            raise RecordNotFoundError(batch_id, external_id)
        return record_model

    def _resolve_call_attempt(
        self, record_model: ValidationRecordModel, provider_call_id: str | None
    ) -> CallAttemptModel:
        if provider_call_id:
            for attempt in record_model.call_attempts:
                if attempt.provider_call_id == provider_call_id:
                    return attempt

        if record_model.call_attempts:
            return record_model.call_attempts[-1]

        attempt = CallAttemptModel(
            attempt_number=1,
            provider_call_id=provider_call_id,
            phone_dialed=record_model.phone_normalized or record_model.phone_original,
            phone_source=CallPhoneSource.PAYLOAD_PHONE,
            status=CallStatus.NOT_STARTED,
            result=CallResult.NOT_STARTED,
            started_at=datetime.now(timezone.utc),
            observation="Tentativa criada a partir do webhook de chamada.",
        )
        record_model.call_attempts.append(attempt)
        return attempt

    def _queue_call_attempt(
        self,
        *,
        record_model: ValidationRecordModel,
        phone_to_dial: str,
        phone_source: CallPhoneSource,
        business_status: BusinessStatus,
        observation: str,
    ) -> CallAttemptModel:
        attempt_number = len(record_model.call_attempts) + 1
        logger.info(
            "Enfileirando tentativa de ligacao | batch_id=%s external_id=%s attempt_number=%s phone=%s phone_source=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            attempt_number,
            phone_to_dial,
            phone_source,
        )
        attempt = CallAttemptModel(
            attempt_number=attempt_number,
            provider_call_id=f"call_{uuid4().hex[:12]}",
            phone_dialed=phone_to_dial,
            phone_source=phone_source,
            status=CallStatus.QUEUED,
            result=CallResult.PENDING_DISPATCH,
            started_at=datetime.now(timezone.utc),
            observation=observation,
        )
        record_model.call_attempts.append(attempt)
        record_model.technical_status = TechnicalStatus.PROCESSING
        record_model.business_status = business_status
        record_model.call_status = CallStatus.QUEUED
        record_model.call_result = CallResult.PENDING_DISPATCH
        record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
        record_model.final_status = FinalStatus.PROCESSING
        record_model.phone_confirmed = False
        record_model.confirmation_source = None
        record_model.observation = observation
        return attempt

    def _lookup_alternative_phone(self, record_model: ValidationRecordModel) -> str | None:
        excluded_phones = {
            normalize_phone(record_model.phone_original) or "",
            record_model.phone_normalized or "",
        }
        excluded_phones.update(
            normalize_phone(attempt.phone_dialed or "") or ""
            for attempt in record_model.call_attempts
        )

        logger.info(
            "Consultando base oficial para telefone alternativo | batch_id=%s external_id=%s",
            record_model.batch.batch_id,
            record_model.external_id,
        )
        return self.official_company_registry.find_alternative_phone(
            cnpj=record_model.cnpj_normalized or record_model.cnpj_original,
            client_name=record_model.client_name,
            excluded_phones=excluded_phones,
        )

    def _ensure_whatsapp_fallback(
        self,
        record_model: ValidationRecordModel,
        target_phone: str | None,
    ) -> None:
        has_pending_fallback = any(
            message.direction == "outbound"
            and message.status in {WhatsAppStatus.SENT, WhatsAppStatus.WAITING_REPLY}
            for message in record_model.whatsapp_messages
        )
        if has_pending_fallback:
            logger.info(
                "Fallback WhatsApp ja existente, nao sera duplicado | batch_id=%s external_id=%s",
                record_model.batch.batch_id,
                record_model.external_id,
            )
            return

        phone_label = (
            target_phone or record_model.phone_normalized or record_model.phone_original
        )
        logger.info(
            "Criando fallback WhatsApp | batch_id=%s external_id=%s target_phone=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            phone_label,
        )
        record_model.whatsapp_messages.append(
            WhatsAppMessageModel(
                provider_message_id=f"wa_{uuid4().hex[:12]}",
                direction="outbound",
                message_body=(
                    f"Olá, estamos validando o cadastro da empresa "
                    f"{record_model.client_name}. Este número pertence à empresa?"
                ),
                status=WhatsAppStatus.SENT,
                sent_at=datetime.now(timezone.utc),
                observation=(
                    f"Mensagem de fallback enviada apos nao atendimento da ligacao para {phone_label}."
                ),
            )
        )

    def _resolve_whatsapp_message(
        self, record_model: ValidationRecordModel, provider_message_id: str | None
    ) -> WhatsAppMessageModel:
        if provider_message_id:
            for message in record_model.whatsapp_messages:
                if message.provider_message_id == provider_message_id:
                    return message

        if record_model.whatsapp_messages:
            return record_model.whatsapp_messages[-1]

        message = WhatsAppMessageModel(
            provider_message_id=provider_message_id,
            direction="inbound",
            status=WhatsAppStatus.WAITING_REPLY,
            observation="Mensagem criada a partir do webhook de WhatsApp.",
        )
        record_model.whatsapp_messages.append(message)
        return message

    def _is_placeholder_call_id(self, provider_call_id: str | None) -> bool:
        return not provider_call_id or provider_call_id.startswith("call_")
