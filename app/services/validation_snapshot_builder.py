from datetime import datetime, timezone
import logging

from ..domain.statuses import (
    BatchStatus,
    BusinessStatus,
    CallResult,
    CallStatus,
    EmailStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)
from ..schemas.request import ValidationBatchRequest, ValidationRecordRequest
from ..schemas.response import (
    ValidationBatchResponse,
    ValidationBatchSummary,
    ValidationRecordResponse,
)
from ..utils.email import normalize_email
from .cnpj import is_valid_cnpj, normalize_cnpj
from .official_company_registry_service import OfficialCompanyRegistryService
from .phone import classify_phone, normalize_phone

logger = logging.getLogger(__name__)


class ValidationSnapshotBuilder:
    def __init__(
        self,
        official_company_registry: OfficialCompanyRegistryService,
    ) -> None:
        self.official_company_registry = official_company_registry

    def build_batch_snapshot(
        self,
        payload: ValidationBatchRequest,
        *,
        account_id: int | None = None,
        api_token_id: int | None = None,
        caller_company_name: str | None = None,
    ) -> ValidationBatchResponse:
        snapshot_time = datetime.now(timezone.utc)
        logger.info(
            "Montando snapshot inicial do lote | batch_id=%s records=%s",
            payload.batch_id,
            len(payload.records),
        )
        processed_records = [
            self._build_record_snapshot(record) for record in payload.records
        ]

        technical_status = (
            TechnicalStatus.RECEIVED
            if any(
                record.technical_status == TechnicalStatus.RECEIVED
                for record in processed_records
            )
            else TechnicalStatus.COMPLETED
        )

        logger.info(
            "Snapshot do lote concluido | batch_id=%s technical_status=%s",
            payload.batch_id,
            technical_status,
        )

        return ValidationBatchResponse(
            batch_id=payload.batch_id,
            account_id=account_id,
            api_token_id=api_token_id,
            caller_company_name=caller_company_name,
            source=payload.source.value,
            batch_status=(
                BatchStatus.RECEIVED
                if technical_status == TechnicalStatus.RECEIVED
                else BatchStatus.COMPLETED
            ),
            processed_at=snapshot_time,
            created_at=snapshot_time,
            updated_at=snapshot_time,
            finished_at=(
                snapshot_time if technical_status == TechnicalStatus.COMPLETED else None
            ),
            result_ready=technical_status == TechnicalStatus.COMPLETED,
            technical_status=technical_status,
            total_records=len(processed_records),
            summary=self._build_summary(processed_records),
            records=processed_records,
        )

    def _build_record_snapshot(
        self, record: ValidationRecordRequest
    ) -> ValidationRecordResponse:
        normalized_cnpj = normalize_cnpj(record.cnpj)
        normalized_phone = normalize_phone(record.phone)
        phone_type = classify_phone(record.phone)
        normalized_email = normalize_email(record.email)

        logger.info(
            "Pre-validando registro | external_id=%s client_name=%s cnpj=%s phone=%s email=%s",
            record.external_id,
            record.client_name,
            normalized_cnpj,
            normalized_phone,
            normalized_email,
        )

        if not is_valid_cnpj(normalized_cnpj):
            logger.warning(
                "CNPJ invalido na validacao estrutural | external_id=%s cnpj=%s",
                record.external_id,
                record.cnpj,
            )
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj or None,
                normalized_phone=normalized_phone,
                phone_type=phone_type,
                normalized_email=normalized_email,
                official_registry_email=None,
                cnpj_found=False,
                phone_valid=normalized_phone is not None,
                business_status=BusinessStatus.VALIDATION_FAILED,
                observation="CNPJ invalido na validacao estrutural.",
            )

        logger.info(
            "Consultando base oficial por CNPJ | external_id=%s cnpj=%s",
            record.external_id,
            normalized_cnpj,
        )
        cnpj_exists = self.official_company_registry.exists(normalized_cnpj)
        if not cnpj_exists:
            logger.warning(
                "CNPJ nao encontrado na base oficial | external_id=%s cnpj=%s",
                record.external_id,
                normalized_cnpj,
            )
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj,
                normalized_phone=normalized_phone,
                phone_type=phone_type,
                normalized_email=normalized_email,
                official_registry_email=None,
                cnpj_found=False,
                phone_valid=normalized_phone is not None,
                business_status=BusinessStatus.CNPJ_NOT_FOUND,
                observation=(
                    "CNPJ nao localizado na base oficial de empresas consultada via BrasilAPI."
                ),
            )

        official_registry_email = self.official_company_registry.find_contact_email(
            cnpj=normalized_cnpj,
        )

        if normalized_phone is None:
            logger.warning(
                "Telefone invalido apos padronizacao | external_id=%s phone_original=%s",
                record.external_id,
                record.phone,
            )
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj,
                normalized_phone=None,
                phone_type=phone_type,
                normalized_email=normalized_email,
                official_registry_email=official_registry_email,
                cnpj_found=True,
                phone_valid=False,
                business_status=BusinessStatus.INVALID_PHONE,
                observation="Telefone invalido apos a padronizacao.",
            )

        logger.info(
            "Registro apto para contato | external_id=%s cnpj=%s phone=%s phone_type=%s",
            record.external_id,
            normalized_cnpj,
            normalized_phone,
            phone_type,
        )
        return ValidationRecordResponse(
            external_id=record.external_id,
            client_name=record.client_name,
            cnpj_original=record.cnpj,
            cnpj_normalized=normalized_cnpj,
            phone_original=record.phone,
            phone_normalized=normalized_phone,
            phone_type=phone_type,
            email_original=record.email,
            email_normalized=normalized_email,
            official_registry_email=official_registry_email,
            fallback_email_used=None,
            cnpj_found=True,
            phone_valid=True,
            ready_for_contact=True,
            technical_status=TechnicalStatus.RECEIVED,
            business_status=BusinessStatus.READY_FOR_CALL,
            call_status=CallStatus.NOT_STARTED,
            call_result=CallResult.NOT_STARTED,
            transcript_summary=None,
            sentiment=None,
            whatsapp_status=WhatsAppStatus.NOT_REQUIRED,
            email_status=EmailStatus.NOT_REQUIRED,
            phone_confirmed=False,
            confirmation_source=None,
            final_status=FinalStatus.PROCESSING,
            observation="Registro recebido e aguardando primeira ligacao de validacao.",
        )

    def _build_failed_record(
        self,
        *,
        record: ValidationRecordRequest,
        normalized_cnpj: str | None,
        normalized_phone: str | None,
        phone_type: str | None,
        normalized_email: str | None,
        official_registry_email: str | None,
        cnpj_found: bool,
        phone_valid: bool,
        business_status: BusinessStatus,
        observation: str,
    ) -> ValidationRecordResponse:
        return ValidationRecordResponse(
            external_id=record.external_id,
            client_name=record.client_name,
            cnpj_original=record.cnpj,
            cnpj_normalized=normalized_cnpj,
            phone_original=record.phone,
            phone_normalized=normalized_phone,
            phone_type=phone_type,
            email_original=record.email,
            email_normalized=normalized_email,
            official_registry_email=official_registry_email,
            fallback_email_used=None,
            cnpj_found=cnpj_found,
            phone_valid=phone_valid,
            ready_for_contact=False,
            technical_status=TechnicalStatus.COMPLETED,
            business_status=business_status,
            call_status=CallStatus.NOT_STARTED,
            call_result=CallResult.NOT_STARTED,
            transcript_summary=None,
            sentiment=None,
            whatsapp_status=WhatsAppStatus.NOT_REQUIRED,
            email_status=EmailStatus.NOT_REQUIRED,
            phone_confirmed=False,
            confirmation_source=None,
            final_status=FinalStatus.VALIDATION_FAILED,
            observation=observation,
        )

    def _build_summary(
        self, records: list[ValidationRecordResponse]
    ) -> ValidationBatchSummary:
        return ValidationBatchSummary(
            ready_for_call=sum(
                record.business_status == BusinessStatus.READY_FOR_CALL
                for record in records
            ),
            ready_for_retry_call=sum(
                record.business_status == BusinessStatus.READY_FOR_RETRY_CALL
                for record in records
            ),
            validation_failed=sum(
                record.final_status == FinalStatus.VALIDATION_FAILED
                for record in records
            ),
            invalid_phone=sum(
                record.business_status == BusinessStatus.INVALID_PHONE
                for record in records
            ),
            cnpj_not_found=sum(
                record.business_status == BusinessStatus.CNPJ_NOT_FOUND
                for record in records
            ),
            processing=sum(
                record.final_status == FinalStatus.PROCESSING for record in records
            ),
            pending_records=sum(
                record.final_status == FinalStatus.PROCESSING for record in records
            ),
            validated_records=sum(
                record.final_status == FinalStatus.VALIDATED for record in records
            ),
            failed_records=sum(
                record.final_status == FinalStatus.VALIDATION_FAILED
                for record in records
            ),
            confirmed_by_call=sum(
                record.business_status == BusinessStatus.CONFIRMED_BY_CALL
                for record in records
            ),
            confirmed_by_whatsapp=sum(
                record.business_status == BusinessStatus.CONFIRMED_BY_WHATSAPP
                for record in records
            ),
            waiting_whatsapp_reply=sum(
                record.business_status == BusinessStatus.WAITING_WHATSAPP_REPLY
                for record in records
            ),
            confirmed_by_email=sum(
                record.business_status == BusinessStatus.CONFIRMED_BY_EMAIL
                for record in records
            ),
            waiting_email_reply=sum(
                record.business_status == BusinessStatus.WAITING_EMAIL_REPLY
                for record in records
            ),
        )
