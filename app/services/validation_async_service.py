from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from ..db.models import (
    CallAttemptModel,
    EmailMessageModel,
    ValidationRecordModel,
    WhatsAppMessageModel,
)
from ..domain.statuses import (
    BusinessStatus,
    CallPhoneSource,
    CallResult,
    CallStatus,
    EmailStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)
from ..core.memory_store import LocalTestMemoryStore
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.async_events import CallEventRequest, WhatsAppEventRequest
from ..schemas.response import ValidationBatchResponse, ValidationRecordResponse
from .errors import BatchNotFoundError, ProviderRequestError, RecordNotFoundError
from .email_service import EmailService
from .official_company_registry_service import OfficialCompanyRegistryService
from .phone import normalize_phone
from ..utils.email import normalize_email
from .twilio_voice_service import TwilioVoiceService, TwimlMode

logger = logging.getLogger(__name__)


class ValidationAsyncService:
    _stopped_batch_ids: set[str] = set()
    _DEFAULT_TWILIO_SLOT = "__default_twilio_slot__"

    def __init__(
        self,
        *,
        batch_repository: ValidationBatchRepository,
        official_company_registry: OfficialCompanyRegistryService,
        twilio_voice_service: TwilioVoiceService,
        email_service: EmailService,
        memory_store: LocalTestMemoryStore | None = None,
    ) -> None:
        self.batch_repository = batch_repository
        self.official_company_registry = official_company_registry
        self.twilio_voice_service = twilio_voice_service
        self.email_service = email_service
        self.memory_store = memory_store

    @classmethod
    def clear_stopped_batches(cls) -> None:
        cls._stopped_batch_ids.clear()

    def dispatch_batch(
        self,
        batch_id: str,
        *,
        account_id: int | None = None,
        twiml_mode: TwimlMode = "media_stream",
        realtime_model_override: str | None = None,
        realtime_voice_override: str | None = None,
        realtime_output_speed_override: float | None = None,
        realtime_style_profile: str | None = None,
    ) -> ValidationBatchResponse:
        logger.info("Iniciando dispatch do lote | batch_id=%s twiml_mode=%s", batch_id, twiml_mode)
        batch_model = (
            self.batch_repository.get_batch_model_for_account(batch_id, account_id)
            if account_id is not None
            else self.batch_repository.get_batch_model(batch_id)
        )
        if batch_model is None:
            logger.warning("Dispatch falhou, lote nao encontrado | batch_id=%s", batch_id)
            raise BatchNotFoundError(batch_id)

        if self._is_batch_stopped(batch_id):
            logger.warning(
                "Dispatch ignorado porque o lote foi encerrado manualmente na UI de teste | batch_id=%s",
                batch_id,
            )
            return self.batch_repository.save_batch(batch_model)

        self._store_batch_realtime_profile(
            batch_id,
            realtime_model_override=realtime_model_override,
            realtime_voice_override=realtime_voice_override,
            realtime_output_speed_override=realtime_output_speed_override,
            realtime_style_profile=realtime_style_profile,
        )

        self._ensure_initial_call_attempts(batch_model)
        self._dispatch_next_pending_attempt(batch_model, twiml_mode=twiml_mode)

        return self.batch_repository.save_batch(batch_model)

    def stop_batch(self, batch_id: str) -> ValidationBatchResponse:
        logger.warning(
            "Encerramento manual do lote solicitado na UI de teste | batch_id=%s",
            batch_id,
        )
        batch_model = self.batch_repository.get_batch_model(batch_id)
        if batch_model is None:
            logger.warning("Encerramento manual falhou, lote nao encontrado | batch_id=%s", batch_id)
            raise BatchNotFoundError(batch_id)

        self._mark_batch_stopped(batch_id)
        stop_time = datetime.now(timezone.utc)
        active_provider_call_ids: set[str] = set()

        for record_model in batch_model.records:
            has_active_attempt = False
            canceled_pending_attempt = False

            for attempt in record_model.call_attempts:
                if (
                    not self._is_placeholder_call_id(attempt.provider_call_id)
                    and attempt.finished_at is None
                ):
                    has_active_attempt = True
                    if attempt.provider_call_id:
                        active_provider_call_ids.add(attempt.provider_call_id)
                    attempt.observation = (
                        "Encerramento manual do lote solicitado na UI de teste. A chamada ativa sera finalizada e nenhuma nova tentativa sera disparada."
                    )
                    continue

                if (
                    attempt.status == CallStatus.QUEUED
                    and attempt.result == CallResult.PENDING_DISPATCH
                    and self._is_placeholder_call_id(attempt.provider_call_id)
                ):
                    canceled_pending_attempt = True
                    attempt.status = CallStatus.FAILED
                    attempt.result = CallResult.INCONCLUSIVE
                    attempt.finished_at = stop_time
                    attempt.observation = (
                        "Tentativa removida da fila por encerramento manual do lote na UI de teste."
                    )

            if record_model.final_status != FinalStatus.PROCESSING:
                continue

            if has_active_attempt:
                record_model.observation = (
                    "Encerramento manual do lote solicitado. A chamada atual sera encerrada e nenhuma nova tentativa sera disparada."
                )
                continue

            if canceled_pending_attempt:
                self._apply_manual_stop_to_record(
                    record_model,
                    observation=(
                        "Lote interrompido manualmente na UI de teste antes da conclusao da chamada."
                    ),
                    call_status=CallStatus.FAILED,
                    call_result=CallResult.INCONCLUSIVE,
                )

        twilio_service = self._resolve_twilio_service_for_batch(batch_model)
        if active_provider_call_ids and twilio_service.is_configured():
            for provider_call_id in sorted(active_provider_call_ids):
                try:
                    twilio_service.end_outbound_call(provider_call_id=provider_call_id)
                except ProviderRequestError as error:
                    logger.exception(
                        "Falha ao solicitar encerramento da chamada ativa do lote | batch_id=%s provider_call_id=%s error=%s",
                        batch_id,
                        provider_call_id,
                        error,
                    )

        self._clear_batch_realtime_profile(batch_id)
        return self.batch_repository.save_batch(batch_model)

    def register_call_event(
        self,
        batch_id: str,
        external_id: str,
        payload: CallEventRequest,
        *,
        account_id: int | None = None,
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

        batch_stopped = self._is_batch_stopped(batch_id)

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
            record_model.email_status = EmailStatus.NOT_REQUIRED
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
            if batch_stopped:
                logger.warning(
                    "Lote interrompido manualmente; rejeicao nao acionara nova tentativa | batch_id=%s external_id=%s",
                    batch_id,
                    external_id,
                )
                self._apply_manual_stop_to_record(
                    record_model,
                    observation=(
                        payload.observation
                        or "Ligacao rejeitou o numero atual, mas o lote foi encerrado manualmente na UI de teste antes de novas tentativas."
                    ),
                    call_status=payload.call_status,
                    call_result=payload.call_result,
                )
            else:
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
                    record_model.email_status = EmailStatus.NOT_REQUIRED
                    record_model.final_status = FinalStatus.VALIDATION_FAILED
                    record_model.observation = (
                        payload.observation
                        or "Numero recusado na ligacao e nenhum telefone alternativo foi encontrado na base oficial de empresas."
                    )
        elif (
            payload.call_status == CallStatus.NOT_ANSWERED
            or payload.call_result == CallResult.NOT_ANSWERED
        ):
            if batch_stopped:
                logger.warning(
                    "Lote interrompido manualmente; nao sera acionado fallback por e-mail | batch_id=%s external_id=%s",
                    batch_id,
                    external_id,
                )
                self._apply_manual_stop_to_record(
                    record_model,
                    observation=(
                        payload.observation
                        or "Ligacao nao atendida, mas o lote foi encerrado manualmente na UI de teste antes do fallback por e-mail."
                    ),
                    call_status=payload.call_status,
                    call_result=payload.call_result,
                )
            else:
                fallback_email = self._resolve_fallback_email(record_model)
                if fallback_email is None:
                    logger.warning(
                        "Ligacao nao atendida e nenhum e-mail de fallback foi encontrado | batch_id=%s external_id=%s",
                        batch_id,
                        external_id,
                    )
                    record_model.technical_status = TechnicalStatus.COMPLETED
                    record_model.business_status = BusinessStatus.CALL_NOT_ANSWERED
                    record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                    record_model.email_status = EmailStatus.NOT_REQUIRED
                    record_model.final_status = FinalStatus.VALIDATION_FAILED
                    record_model.observation = (
                        payload.observation
                        or "Ligacao nao atendida e nenhum e-mail de fallback foi encontrado no payload nem na base oficial."
                    )
                else:
                    logger.info(
                        "Ligacao nao atendida, acionando fallback por e-mail | batch_id=%s external_id=%s fallback_email=%s",
                        batch_id,
                        external_id,
                        fallback_email,
                    )
                    email_sent = self._ensure_email_fallback(record_model, fallback_email)
                    if email_sent:
                        record_model.technical_status = TechnicalStatus.PROCESSING
                        record_model.business_status = BusinessStatus.WAITING_EMAIL_REPLY
                        record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                        record_model.email_status = EmailStatus.WAITING_REPLY
                        record_model.final_status = FinalStatus.PROCESSING
                        record_model.observation = (
                            payload.observation
                            or "Ligacao nao atendida. Fallback por e-mail foi acionado e o lote aguarda retorno do contato."
                        )
                    else:
                        record_model.technical_status = TechnicalStatus.COMPLETED
                        record_model.business_status = BusinessStatus.CALL_NOT_ANSWERED
                        record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                        record_model.email_status = EmailStatus.FAILED
                        record_model.final_status = FinalStatus.VALIDATION_FAILED
                        record_model.observation = (
                            payload.observation
                            or "Ligacao nao atendida e o fallback por e-mail falhou ao ser enviado."
                        )
        else:
            logger.info(
                "Ligacao inconclusiva | batch_id=%s external_id=%s",
                batch_id,
                external_id,
            )
            if batch_stopped:
                self._apply_manual_stop_to_record(
                    record_model,
                    observation=(
                        payload.observation
                        or "Ligacao inconclusiva e lote encerrado manualmente na UI de teste. Nenhuma nova tentativa sera disparada."
                    ),
                    call_status=payload.call_status,
                    call_result=payload.call_result,
                )
            else:
                record_model.technical_status = TechnicalStatus.PROCESSING
                record_model.business_status = BusinessStatus.INCONCLUSIVE_CALL
                record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
                record_model.email_status = EmailStatus.NOT_REQUIRED
                record_model.final_status = FinalStatus.PROCESSING
                record_model.observation = (
                    payload.observation
                    or "Ligacao inconclusiva. Fluxo aguardando tratativa adicional antes do encerramento."
                )

        self._dispatch_next_pending_attempt(record_model.batch)
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
                record_model.email_status = EmailStatus.NOT_REQUIRED
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

            self._dispatch_next_pending_attempt(record_model.batch)
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
        *,
        account_id: int | None = None,
    ) -> ValidationRecordResponse:
        logger.info(
            "Registrando evento de WhatsApp | batch_id=%s external_id=%s provider_message_id=%s status=%s direction=%s",
            batch_id,
            external_id,
            payload.provider_message_id,
            payload.status,
            payload.direction,
        )
        record_model = self._get_record_model(batch_id, external_id, account_id=account_id)
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

        self._dispatch_next_pending_attempt(record_model.batch)
        return self.batch_repository.save_record(record_model)

    def _ensure_initial_call_attempts(self, batch_model) -> None:
        if self._is_batch_stopped(batch_model.batch_id):
            logger.warning(
                "Lote encerrado manualmente na UI de teste; tentativas iniciais nao serao enfileiradas | batch_id=%s",
                batch_model.batch_id,
            )
            return

        for record in batch_model.records:
            logger.info(
                "Avaliando registro para dispatch | batch_id=%s external_id=%s ready_for_contact=%s final_status=%s",
                batch_model.batch_id,
                record.external_id,
                record.ready_for_contact,
                record.final_status,
            )
            if not record.ready_for_contact or record.final_status != FinalStatus.PROCESSING:
                continue
            if record.call_attempts:
                continue

            self._queue_call_attempt(
                record_model=record,
                phone_to_dial=record.phone_normalized or record.phone_original,
                phone_source=CallPhoneSource.PAYLOAD_PHONE,
                business_status=BusinessStatus.READY_FOR_CALL,
                observation="Ligacao inicial enfileirada para validacao por voz.",
            )

    def _dispatch_next_pending_attempt(self, batch_model, *, twiml_mode: TwimlMode = "media_stream") -> bool:
        if self._is_batch_stopped(batch_model.batch_id):
            logger.warning(
                "Lote encerrado manualmente na UI de teste; nenhuma nova tentativa sera despachada | batch_id=%s",
                batch_model.batch_id,
            )
            return False

        dispatched_any = False
        while True:
            next_item = self._find_next_pending_attempt(batch_model)
            if next_item is None:
                logger.info(
                    "Nenhuma tentativa pendente na fila do lote | batch_id=%s",
                    batch_model.batch_id,
                )
                if not self._has_active_voice_attempt(batch_model):
                    self._clear_batch_realtime_profile(batch_model.batch_id)
                return dispatched_any

            available_slots = self._resolve_twilio_capacity_by_phone(batch_model)
            if not available_slots:
                logger.warning(
                    "Nenhum telefone Twilio ativo disponivel para o lote | batch_id=%s",
                    batch_model.batch_id,
                )
                return dispatched_any

            from_phone_number_used = self._get_next_available_from_phone(batch_model)
            if from_phone_number_used is None:
                logger.info(
                    "Toda a capacidade de linhas Twilio do lote esta ocupada; tentativa seguira na fila | batch_id=%s",
                    batch_model.batch_id,
                )
                return dispatched_any

            record_model, call_attempt = next_item
            logger.info(
                "Despachando proxima tentativa da fila do lote | batch_id=%s external_id=%s attempt_number=%s phone=%s from_phone=%s",
                batch_model.batch_id,
                record_model.external_id,
                call_attempt.attempt_number,
                call_attempt.phone_dialed,
                from_phone_number_used,
            )
            dispatched = self._dispatch_voice_attempt(
                record_model,
                call_attempt,
                from_phone_number_used=from_phone_number_used,
                twiml_mode=twiml_mode,
                realtime_profile=self._get_batch_realtime_profile(batch_model.batch_id),
            )
            if not dispatched:
                return dispatched_any
            dispatched_any = True

    def _has_active_voice_attempt(self, batch_model) -> bool:
        for record in batch_model.records:
            for attempt in record.call_attempts:
                if (
                    not self._is_placeholder_call_id(attempt.provider_call_id)
                    and attempt.finished_at is None
                ):
                    return True
        return False

    def _find_next_pending_attempt(
        self,
        batch_model,
    ) -> tuple[ValidationRecordModel, CallAttemptModel] | None:
        pending_attempts: list[tuple[int, int, int, ValidationRecordModel, CallAttemptModel]] = []

        for record_index, record in enumerate(batch_model.records):
            for attempt in record.call_attempts:
                if (
                    attempt.status == CallStatus.QUEUED
                    and attempt.result == CallResult.PENDING_DISPATCH
                    and self._is_placeholder_call_id(attempt.provider_call_id)
                ):
                    pending_attempts.append(
                        (
                            attempt.attempt_number,
                            record_index,
                            attempt.id or 0,
                            record,
                            attempt,
                        )
                    )

        if not pending_attempts:
            return None

        _, _, _, record_model, call_attempt = min(pending_attempts)
        return record_model, call_attempt

    def _dispatch_voice_attempt(
        self,
        record_model: ValidationRecordModel,
        call_attempt: CallAttemptModel,
        *,
        from_phone_number_used: str | None,
        twiml_mode: TwimlMode = "media_stream",
        realtime_profile: dict[str, object] | None = None,
    ) -> bool:
        twilio_service = self._resolve_twilio_service_for_batch(record_model.batch)
        if not twilio_service.is_configured():
            logger.info(
                "Provedor de voz nao configurado, mantendo tentativa em modo manual | batch_id=%s external_id=%s attempt_number=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                call_attempt.attempt_number,
            )
            call_attempt.from_phone_number_used = None
            return False

        if not self._is_placeholder_call_id(call_attempt.provider_call_id):
            logger.info(
                "Tentativa ja possui provider_call_id real, nao sera reenviada | batch_id=%s external_id=%s provider_call_id=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                call_attempt.provider_call_id,
            )
            return False

        resolved_from_phone_number = (
            None if from_phone_number_used == self._DEFAULT_TWILIO_SLOT else from_phone_number_used
        )
        logger.info(
            "Enviando tentativa ao provedor de voz | batch_id=%s external_id=%s attempt_number=%s phone=%s from_phone=%s twiml_mode=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            call_attempt.attempt_number,
            call_attempt.phone_dialed or record_model.phone_original,
            resolved_from_phone_number,
            twiml_mode,
        )
        call_attempt.from_phone_number_used = resolved_from_phone_number
        try:
            create_call_kwargs: dict[str, object] = {
                "batch_id": record_model.batch.batch_id,
                "external_id": record_model.external_id,
                "attempt_number": call_attempt.attempt_number,
                "caller_company_name": self._resolve_caller_company_name(record_model.batch),
                "client_name": record_model.client_name,
                "cnpj": record_model.cnpj_normalized or record_model.cnpj_original,
                "phone_to_dial": call_attempt.phone_dialed or record_model.phone_original,
                "from_phone_number_override": resolved_from_phone_number,
                "twiml_mode": twiml_mode,
            }
            if realtime_profile:
                if realtime_profile.get("realtime_model_override"):
                    create_call_kwargs["realtime_model_override"] = realtime_profile["realtime_model_override"]
                if realtime_profile.get("realtime_voice_override"):
                    create_call_kwargs["realtime_voice_override"] = realtime_profile["realtime_voice_override"]
                if realtime_profile.get("realtime_output_speed_override") is not None:
                    create_call_kwargs["realtime_output_speed_override"] = realtime_profile["realtime_output_speed_override"]
                if realtime_profile.get("realtime_style_profile"):
                    create_call_kwargs["realtime_style_profile"] = realtime_profile["realtime_style_profile"]

            dispatch_result = twilio_service.create_outbound_call(**create_call_kwargs)
        except ProviderRequestError as error:
            logger.exception(
                "Falha ao enviar chamada ao provedor de voz | batch_id=%s external_id=%s error=%s status_code=%s provider_code=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                error,
                error.status_code,
                error.provider_code,
            )
            if self._handle_provider_dispatch_error(record_model, call_attempt, error):
                self._dispatch_next_pending_attempt(record_model.batch, twiml_mode=twiml_mode)
            return False

        call_attempt.provider_call_id = dispatch_result.provider_call_id
        logger.info(
            "Tentativa enviada ao provedor de voz | batch_id=%s external_id=%s provider_call_id=%s provider_status=%s from_phone=%s",
            record_model.batch.batch_id,
            record_model.external_id,
            dispatch_result.provider_call_id,
            dispatch_result.provider_status,
            resolved_from_phone_number,
        )
        call_attempt.observation = (
            "Ligacao enviada ao provedor de voz e aguardando eventos reais da chamada."
        )
        record_model.observation = call_attempt.observation
        return True

    def _handle_provider_dispatch_error(
        self,
        record_model: ValidationRecordModel,
        call_attempt: CallAttemptModel,
        error: ProviderRequestError,
    ) -> bool:
        call_attempt.from_phone_number_used = None
        call_attempt.status = CallStatus.FAILED
        call_attempt.result = CallResult.INCONCLUSIVE
        call_attempt.finished_at = datetime.now(timezone.utc)

        if (
            error.provider_name == "Twilio Voice"
            and error.provider_code == "21219"
            and call_attempt.phone_source == CallPhoneSource.OFFICIAL_COMPANY_REGISTRY
        ):
            logger.warning(
                "Telefone alternativo da base oficial nao pode ser discado em conta trial do Twilio; tentativa sera encerrada sem novo retry | batch_id=%s external_id=%s phone=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                call_attempt.phone_dialed,
            )
            call_attempt.observation = (
                "Telefone alternativo encontrado na base oficial, mas a conta trial do Twilio nao pode ligar para numeros nao verificados (erro 21219)."
            )
            record_model.technical_status = TechnicalStatus.COMPLETED
            record_model.business_status = BusinessStatus.REJECTED_BY_CALL
            record_model.call_status = CallStatus.FAILED
            record_model.call_result = CallResult.INCONCLUSIVE
            record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
            record_model.email_status = EmailStatus.NOT_REQUIRED
            record_model.phone_confirmed = False
            record_model.confirmation_source = None
            record_model.final_status = FinalStatus.VALIDATION_FAILED
            record_model.observation = (
                "Numero recusado na ligacao inicial. A base oficial retornou telefone alternativo, mas a conta trial do Twilio nao pode discar para numeros nao verificados."
            )
            return True

        call_attempt.observation = (
            f"{call_attempt.observation} Provedor de voz retornou erro temporario: {error}"
        )
        record_model.observation = call_attempt.observation
        return False

    def _resolve_caller_company_name(self, batch_model) -> str:
        if getattr(batch_model, "caller_company_name", None):
            return batch_model.caller_company_name

        platform_account = getattr(batch_model, "platform_account", None)
        if platform_account is not None:
            if getattr(platform_account, "spoken_company_name", None):
                return platform_account.spoken_company_name
            if getattr(platform_account, "company_name", None):
                return platform_account.company_name

        return "Central de Validacao Cadastral"

    def _resolve_twilio_service_for_batch(self, batch_model) -> TwilioVoiceService:
        if getattr(batch_model, "platform_account_id", None) is None:
            return self.twilio_voice_service

        platform_account = getattr(batch_model, "platform_account", None)
        twilio_credential = getattr(platform_account, "twilio_credential", None) if platform_account is not None else None
        active_phone_numbers = [
            phone.phone_number
            for phone in getattr(platform_account, "twilio_phone_numbers", [])
            if phone.is_active and phone.phone_number
        ]
        default_from_phone = active_phone_numbers[0] if active_phone_numbers else None
        webhook_base_url = (
            getattr(twilio_credential, "webhook_base_url", None)
            or self.twilio_voice_service.webhook_base_url
        )

        if twilio_credential is None:
            return TwilioVoiceService(
                account_sid=None,
                auth_token=None,
                from_phone_number=default_from_phone,
                webhook_base_url=webhook_base_url,
            )

        return TwilioVoiceService(
            account_sid=twilio_credential.account_sid,
            auth_token=twilio_credential.auth_token,
            from_phone_number=default_from_phone,
            webhook_base_url=webhook_base_url,
        )

    def _resolve_email_service_for_batch(self, batch_model) -> EmailService:
        if getattr(batch_model, "platform_account_id", None) is None:
            return self.email_service

        platform_account = getattr(batch_model, "platform_account", None)
        email_profile = getattr(platform_account, "email_sender_profile", None) if platform_account is not None else None
        caller_company_name = self._resolve_caller_company_name(batch_model)

        if email_profile is not None and email_profile.enabled:
            return EmailService(
                host=email_profile.smtp_host,
                port=email_profile.smtp_port,
                username=email_profile.smtp_username,
                password=email_profile.smtp_password,
                use_tls=email_profile.smtp_use_tls,
                from_address=email_profile.from_address,
                from_name=email_profile.from_name or caller_company_name,
            )

        return EmailService(
            host=None,
            port=587,
            username=None,
            password=None,
            use_tls=True,
            from_address=None,
            from_name=caller_company_name,
        )

    def _resolve_twilio_capacity_by_phone(self, batch_model) -> dict[str | None, int]:
        if getattr(batch_model, "platform_account_id", None) is None:
            return {self._DEFAULT_TWILIO_SLOT: 1}

        platform_account = getattr(batch_model, "platform_account", None)
        capacities: dict[str | None, int] = {}
        for phone in getattr(platform_account, "twilio_phone_numbers", []):
            if not phone.is_active or not phone.phone_number:
                continue
            capacities[phone.phone_number] = max(1, phone.max_concurrent_calls or 1)
        return capacities

    def _count_active_voice_attempts_by_phone(self, batch_model) -> dict[str | None, int]:
        counts: dict[str | None, int] = {}
        default_slot = self._DEFAULT_TWILIO_SLOT if getattr(batch_model, "platform_account_id", None) is None else None
        for record in batch_model.records:
            for attempt in record.call_attempts:
                if (
                    not self._is_placeholder_call_id(attempt.provider_call_id)
                    and attempt.finished_at is None
                ):
                    slot_key = attempt.from_phone_number_used
                    if slot_key is None and default_slot is not None:
                        slot_key = default_slot
                    counts[slot_key] = counts.get(slot_key, 0) + 1
        return counts

    def _get_next_available_from_phone(self, batch_model) -> str | None:
        capacities = self._resolve_twilio_capacity_by_phone(batch_model)
        if not capacities:
            return None

        active_counts = self._count_active_voice_attempts_by_phone(batch_model)
        for from_phone_number, capacity in capacities.items():
            if active_counts.get(from_phone_number, 0) < capacity:
                return from_phone_number
        return None

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
        self, batch_id: str, external_id: str, *, account_id: int | None = None
    ) -> ValidationRecordModel:
        record_model = self.batch_repository.get_record_model(
            batch_id,
            external_id,
            account_id=account_id,
        )

        if record_model is None and account_id is not None:
            fallback_batch = self.batch_repository.get_batch_model_for_public_lookup(batch_id)
            if fallback_batch is not None and fallback_batch.platform_account_id == account_id:
                for candidate in fallback_batch.records:
                    if candidate.external_id == external_id:
                        record_model = candidate
                        break

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
        record_model.email_status = EmailStatus.NOT_REQUIRED
        record_model.final_status = FinalStatus.PROCESSING
        record_model.phone_confirmed = False
        record_model.confirmation_source = None
        record_model.observation = observation
        return attempt

    def _store_batch_realtime_profile(
        self,
        batch_id: str,
        *,
        realtime_model_override: str | None,
        realtime_voice_override: str | None,
        realtime_output_speed_override: float | None,
        realtime_style_profile: str | None,
    ) -> None:
        if self.memory_store is None:
            return

        profile = {
            "realtime_model_override": realtime_model_override,
            "realtime_voice_override": realtime_voice_override,
            "realtime_output_speed_override": realtime_output_speed_override,
            "realtime_style_profile": realtime_style_profile,
        }
        if not any(value is not None for value in profile.values()):
            return
        self.memory_store.set_batch_realtime_profile(batch_id, profile)

    def _get_batch_realtime_profile(self, batch_id: str) -> dict[str, object] | None:
        if self.memory_store is None:
            return None
        return self.memory_store.get_batch_realtime_profile(batch_id)

    def _clear_batch_realtime_profile(self, batch_id: str) -> None:
        if self.memory_store is None:
            return
        self.memory_store.clear_batch_realtime_profile(batch_id)

    def _is_batch_stopped(self, batch_id: str) -> bool:
        return batch_id in type(self)._stopped_batch_ids

    def _mark_batch_stopped(self, batch_id: str) -> None:
        type(self)._stopped_batch_ids.add(batch_id)

    def _apply_manual_stop_to_record(
        self,
        record_model: ValidationRecordModel,
        *,
        observation: str,
        call_status: CallStatus,
        call_result: CallResult,
    ) -> None:
        record_model.technical_status = TechnicalStatus.COMPLETED
        record_model.business_status = BusinessStatus.VALIDATION_FAILED
        record_model.whatsapp_status = WhatsAppStatus.NOT_REQUIRED
        record_model.email_status = EmailStatus.NOT_REQUIRED
        record_model.call_status = call_status
        record_model.call_result = call_result
        record_model.phone_confirmed = False
        record_model.confirmation_source = None
        record_model.final_status = FinalStatus.VALIDATION_FAILED
        record_model.observation = observation

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

    def _resolve_fallback_email(self, record_model: ValidationRecordModel) -> str | None:
        payload_email = normalize_email(record_model.email_normalized or record_model.email_original)
        official_registry_email = normalize_email(record_model.official_registry_email)
        return payload_email or official_registry_email

    def _ensure_email_fallback(
        self,
        record_model: ValidationRecordModel,
        target_email: str,
    ) -> bool:
        has_pending_fallback = any(
            message.direction == "outbound"
            and message.status in {EmailStatus.SENT, EmailStatus.WAITING_REPLY}
            and message.recipient_email == target_email
            for message in record_model.email_messages
        )
        if has_pending_fallback:
            logger.info(
                "Fallback por e-mail ja existente, nao sera duplicado | batch_id=%s external_id=%s target_email=%s",
                record_model.batch.batch_id,
                record_model.external_id,
                target_email,
            )
            return True

        email_service = self._resolve_email_service_for_batch(record_model.batch)
        send_result = email_service.send_validation_fallback_email(
            recipient_email=target_email,
            client_name=record_model.client_name,
            cnpj=record_model.cnpj_normalized or record_model.cnpj_original,
            phone=record_model.phone_normalized or record_model.phone_original,
            caller_company_name=self._resolve_caller_company_name(record_model.batch),
        )
        email_message = EmailMessageModel(
            provider_message_id=send_result.provider_message_id or f"email_{uuid4().hex[:12]}",
            direction="outbound",
            recipient_email=target_email,
            subject=send_result.subject,
            message_body=send_result.message_body,
            status=EmailStatus.WAITING_REPLY if send_result.success else EmailStatus.FAILED,
            sent_at=(datetime.now(timezone.utc) if send_result.success else None),
            observation=(
                f"Fallback por e-mail enviado apos nao atendimento da ligacao para {target_email}."
                if send_result.success
                else f"Falha ao enviar fallback por e-mail para {target_email}: {send_result.error_message}"
            ),
        )
        record_model.email_messages.append(email_message)
        return send_result.success

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
