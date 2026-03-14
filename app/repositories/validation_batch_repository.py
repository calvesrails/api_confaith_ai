from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db.models import ValidationBatchModel, ValidationRecordModel
from ..domain.statuses import BusinessStatus, FinalStatus
from ..schemas.response import (
    ValidationBatchResponse,
    ValidationBatchSummary,
    ValidationRecordResponse,
)


class ValidationBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def exists(self, batch_id: str) -> bool:
        return self._get_batch_model(batch_id) is not None

    def create_from_snapshot(
        self, snapshot: ValidationBatchResponse
    ) -> ValidationBatchResponse:
        batch_model = ValidationBatchModel(
            batch_id=snapshot.batch_id,
            source=snapshot.source,
            technical_status=snapshot.technical_status,
            total_records=snapshot.total_records,
        )

        for record in snapshot.records:
            batch_model.records.append(
                ValidationRecordModel(
                    external_id=record.external_id,
                    supplier_name=record.supplier_name,
                    cnpj_original=record.cnpj_original,
                    cnpj_normalized=record.cnpj_normalized,
                    phone_original=record.phone_original,
                    phone_normalized=record.phone_normalized,
                    phone_type=record.phone_type,
                    cnpj_found=record.cnpj_found,
                    phone_valid=record.phone_valid,
                    ready_for_contact=record.ready_for_contact,
                    technical_status=record.technical_status,
                    business_status=record.business_status,
                    call_status=record.call_status,
                    call_result=record.call_result,
                    transcript_summary=record.transcript_summary,
                    sentiment=record.sentiment,
                    whatsapp_status=record.whatsapp_status,
                    phone_confirmed=record.phone_confirmed,
                    confirmation_source=record.confirmation_source,
                    final_status=record.final_status,
                    observation=record.observation,
                    call_attempts=[],
                    whatsapp_history=[],
                )
            )

        self.session.add(batch_model)
        self.session.commit()
        return self.get_snapshot_by_batch_id(snapshot.batch_id)

    def get_snapshot_by_batch_id(
        self, batch_id: str
    ) -> ValidationBatchResponse | None:
        batch_model = self._get_batch_model(batch_id)
        if batch_model is None:
            return None

        records = [self._map_record(record) for record in batch_model.records]
        return ValidationBatchResponse(
            batch_id=batch_model.batch_id,
            source=batch_model.source,
            processed_at=batch_model.updated_at,
            technical_status=batch_model.technical_status,
            total_records=batch_model.total_records,
            summary=self._build_summary(records),
            records=records,
        )

    def _get_batch_model(self, batch_id: str) -> ValidationBatchModel | None:
        statement = (
            select(ValidationBatchModel)
            .options(selectinload(ValidationBatchModel.records))
            .where(ValidationBatchModel.batch_id == batch_id)
        )
        return self.session.scalars(statement).first()

    def _map_record(self, record: ValidationRecordModel) -> ValidationRecordResponse:
        return ValidationRecordResponse(
            external_id=record.external_id,
            supplier_name=record.supplier_name,
            cnpj_original=record.cnpj_original,
            cnpj_normalized=record.cnpj_normalized,
            phone_original=record.phone_original,
            phone_normalized=record.phone_normalized,
            phone_type=record.phone_type,
            cnpj_found=record.cnpj_found,
            phone_valid=record.phone_valid,
            ready_for_contact=record.ready_for_contact,
            technical_status=record.technical_status,
            business_status=record.business_status,
            call_status=record.call_status,
            call_result=record.call_result,
            transcript_summary=record.transcript_summary,
            sentiment=record.sentiment,
            whatsapp_status=record.whatsapp_status,
            phone_confirmed=record.phone_confirmed,
            confirmation_source=record.confirmation_source,
            final_status=record.final_status,
            observation=record.observation,
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
