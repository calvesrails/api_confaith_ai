from datetime import datetime, timezone

from ..domain.statuses import (
    BusinessStatus,
    CallResult,
    CallStatus,
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
from .cnpj import is_valid_cnpj, normalize_cnpj
from .phone import classify_phone, normalize_phone
from .registry_lookup import RegistryLookupService


class ValidationSnapshotBuilder:
    def __init__(self, registry_lookup: RegistryLookupService) -> None:
        self.registry_lookup = registry_lookup

    def build_batch_snapshot(
        self, payload: ValidationBatchRequest
    ) -> ValidationBatchResponse:
        processed_records = [self._build_record_snapshot(record) for record in payload.records]

        technical_status = (
            TechnicalStatus.PROCESSING
            if any(
                record.technical_status == TechnicalStatus.PROCESSING
                for record in processed_records
            )
            else TechnicalStatus.COMPLETED
        )

        return ValidationBatchResponse(
            batch_id=payload.batch_id,
            source=payload.source.value,
            processed_at=datetime.now(timezone.utc),
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

        if not is_valid_cnpj(normalized_cnpj):
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj or None,
                normalized_phone=normalized_phone,
                phone_type=phone_type,
                cnpj_found=False,
                phone_valid=normalized_phone is not None,
                business_status=BusinessStatus.VALIDATION_FAILED,
                observation="CNPJ invalido na validacao estrutural.",
            )

        if not self.registry_lookup.exists(normalized_cnpj):
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj,
                normalized_phone=normalized_phone,
                phone_type=phone_type,
                cnpj_found=False,
                phone_valid=normalized_phone is not None,
                business_status=BusinessStatus.CNPJ_NOT_FOUND,
                observation="CNPJ nao localizado na base cadastral configurada.",
            )

        if normalized_phone is None:
            return self._build_failed_record(
                record=record,
                normalized_cnpj=normalized_cnpj,
                normalized_phone=None,
                phone_type=phone_type,
                cnpj_found=True,
                phone_valid=False,
                business_status=BusinessStatus.INVALID_PHONE,
                observation="Telefone invalido apos a padronizacao.",
            )

        return ValidationRecordResponse(
            external_id=record.external_id,
            supplier_name=record.supplier_name,
            cnpj_original=record.cnpj,
            cnpj_normalized=normalized_cnpj,
            phone_original=record.phone,
            phone_normalized=normalized_phone,
            phone_type=phone_type,
            cnpj_found=True,
            phone_valid=True,
            ready_for_contact=True,
            technical_status=TechnicalStatus.PROCESSING,
            business_status=BusinessStatus.READY_FOR_CALL,
            call_status=CallStatus.QUEUED,
            call_result=CallResult.PENDING_DISPATCH,
            transcript_summary=None,
            sentiment=None,
            whatsapp_status=WhatsAppStatus.NOT_REQUIRED,
            phone_confirmed=False,
            confirmation_source=None,
            final_status=FinalStatus.PROCESSING,
            observation="Registro apto para iniciar o fluxo de ligacao.",
        )

    def _build_failed_record(
        self,
        *,
        record: ValidationRecordRequest,
        normalized_cnpj: str | None,
        normalized_phone: str | None,
        phone_type: str | None,
        cnpj_found: bool,
        phone_valid: bool,
        business_status: BusinessStatus,
        observation: str,
    ) -> ValidationRecordResponse:
        return ValidationRecordResponse(
            external_id=record.external_id,
            supplier_name=record.supplier_name,
            cnpj_original=record.cnpj,
            cnpj_normalized=normalized_cnpj,
            phone_original=record.phone,
            phone_normalized=normalized_phone,
            phone_type=phone_type,
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
        )
