from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db.models import (
    ValidationBatchModel,
    ValidationRecordModel,
)
from ..domain.statuses import BatchStatus, BusinessStatus, FinalStatus, TechnicalStatus
from ..schemas.response import (
    CallAttemptResponse,
    ValidationBatchResponse,
    ValidationBatchSummary,
    ValidationRecordResponse,
    WhatsAppMessageResponse,
)


class ValidationBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def exists(self, batch_id: str) -> bool:
        return self.get_batch_model(batch_id) is not None

    def create_from_snapshot(
        self, snapshot: ValidationBatchResponse
    ) -> ValidationBatchResponse:
        batch_model = ValidationBatchModel(
            batch_id=snapshot.batch_id,
            source=snapshot.source,
            batch_status=snapshot.batch_status,
            technical_status=snapshot.technical_status,
            total_records=snapshot.total_records,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            finished_at=snapshot.finished_at,
        )

        for record in snapshot.records:
            batch_model.records.append(
                ValidationRecordModel(
                    external_id=record.external_id,
                    client_name=record.client_name,
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
            )

        self._apply_batch_state(batch_model)
        self.session.add(batch_model)
        self.session.commit()
        return self.get_snapshot_by_batch_id(snapshot.batch_id)

    def get_snapshot_by_batch_id(
        self, batch_id: str
    ) -> ValidationBatchResponse | None:
        batch_model = self.get_batch_model(batch_id)
        if batch_model is None:
            return None
        return self.build_batch_response(batch_model)

    def get_batch_model(self, batch_id: str) -> ValidationBatchModel | None:
        statement = (
            select(ValidationBatchModel)
            .options(
                selectinload(ValidationBatchModel.records).selectinload(
                    ValidationRecordModel.call_attempts
                ),
                selectinload(ValidationBatchModel.records).selectinload(
                    ValidationRecordModel.whatsapp_messages
                ),
            )
            .where(ValidationBatchModel.batch_id == batch_id)
        )
        return self.session.scalars(statement).first()

    def get_record_model(
        self, batch_id: str, external_id: str
    ) -> ValidationRecordModel | None:
        batch_model = self.get_batch_model(batch_id)
        if batch_model is None:
            return None

        for record in batch_model.records:
            if record.external_id == external_id:
                return record

        return None

    def save_batch(self, batch_model: ValidationBatchModel) -> ValidationBatchResponse:
        self._apply_batch_state(batch_model)
        self.session.add(batch_model)
        self.session.commit()
        self.session.refresh(batch_model)
        return self.build_batch_response(batch_model)

    def save_record(
        self, record_model: ValidationRecordModel
    ) -> ValidationRecordResponse:
        batch_model = record_model.batch
        self._apply_batch_state(batch_model)
        self.session.add(record_model)
        self.session.commit()
        self.session.refresh(record_model)
        return self.build_record_response(record_model)

    def build_batch_response(
        self, batch_model: ValidationBatchModel
    ) -> ValidationBatchResponse:
        records = [self.build_record_response(record) for record in batch_model.records]
        return ValidationBatchResponse(
            batch_id=batch_model.batch_id,
            source=batch_model.source,
            batch_status=batch_model.batch_status,
            processed_at=batch_model.updated_at,
            created_at=batch_model.created_at,
            updated_at=batch_model.updated_at,
            finished_at=batch_model.finished_at,
            result_ready=batch_model.batch_status == BatchStatus.COMPLETED,
            technical_status=batch_model.technical_status,
            total_records=batch_model.total_records,
            summary=self._build_summary(records),
            records=records,
        )

    def build_record_response(
        self, record: ValidationRecordModel
    ) -> ValidationRecordResponse:
        return ValidationRecordResponse(
            external_id=record.external_id,
            client_name=record.client_name,
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
            call_attempts=[
                CallAttemptResponse(
                    attempt_number=attempt.attempt_number,
                    provider_call_id=attempt.provider_call_id,
                    phone_dialed=attempt.phone_dialed,
                    phone_source=attempt.phone_source,
                    status=attempt.status,
                    result=attempt.result,
                    transcript_summary=attempt.transcript_summary,
                    sentiment=attempt.sentiment,
                    duration_seconds=attempt.duration_seconds,
                    started_at=attempt.started_at,
                    finished_at=attempt.finished_at,
                    observation=attempt.observation,
                )
                for attempt in record.call_attempts
            ],
            whatsapp_history=[
                WhatsAppMessageResponse(
                    provider_message_id=message.provider_message_id,
                    direction=message.direction,
                    message_body=message.message_body,
                    response_text=message.response_text,
                    status=message.status,
                    sent_at=message.sent_at,
                    responded_at=message.responded_at,
                    observation=message.observation,
                )
                for message in record.whatsapp_messages
            ],
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
        )

    def _apply_batch_state(self, batch_model: ValidationBatchModel) -> None:
        batch_status, technical_status = self._calculate_batch_state(batch_model.records)
        now = datetime.now(timezone.utc)

        batch_model.batch_status = batch_status
        batch_model.technical_status = technical_status
        batch_model.total_records = len(batch_model.records)
        batch_model.updated_at = now
        batch_model.finished_at = (
            batch_model.finished_at or now
            if batch_status == BatchStatus.COMPLETED
            else None
        )

    def _calculate_batch_state(
        self, records: list[ValidationRecordModel]
    ) -> tuple[BatchStatus, TechnicalStatus]:
        if all(record.final_status != FinalStatus.PROCESSING for record in records):
            return BatchStatus.COMPLETED, TechnicalStatus.COMPLETED

        if any(record.technical_status == TechnicalStatus.PROCESSING for record in records):
            return BatchStatus.PROCESSING, TechnicalStatus.PROCESSING

        return BatchStatus.RECEIVED, TechnicalStatus.RECEIVED
