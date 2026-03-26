from datetime import datetime, timezone
import hashlib

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..db.models import (
    PlatformAccountModel,
    ValidationBatchModel,
    ValidationRecordModel,
)
from ..domain.statuses import (
    BatchStatus,
    BusinessStatus,
    CallPhoneSource,
    CallResult,
    CallStatus,
    FinalStatus,
    TechnicalStatus,
)
from ..schemas.response import (
    CallAttemptResponse,
    EmailMessageResponse,
    SupplierValidationDetails,
    ValidationBatchResponse,
    ValidationBatchSummary,
    ValidationRecordResponse,
    WhatsAppMessageResponse,
)


def _split_transcript_summary(summary: str | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None

    customer_parts: list[str] = []
    assistant_parts: list[str] = []

    for segment in summary.split(" | "):
        cleaned_segment = segment.strip()
        if cleaned_segment.startswith("cliente:"):
            customer_parts.append(cleaned_segment.split(":", 1)[1].strip())
        elif cleaned_segment.startswith("agente:"):
            assistant_parts.append(cleaned_segment.split(":", 1)[1].strip())

    customer_transcript = " ".join(part for part in customer_parts if part) or None
    assistant_transcript = " ".join(part for part in assistant_parts if part) or None
    return customer_transcript, assistant_transcript


def _deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class ValidationBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _base_batch_statement(self):
        return select(ValidationBatchModel).options(
            selectinload(ValidationBatchModel.records).selectinload(
                ValidationRecordModel.call_attempts
            ),
            selectinload(ValidationBatchModel.records).selectinload(
                ValidationRecordModel.whatsapp_messages
            ),
            selectinload(ValidationBatchModel.records).selectinload(
                ValidationRecordModel.email_messages
            ),
            selectinload(ValidationBatchModel.platform_account).selectinload(
                PlatformAccountModel.twilio_credential
            ),
            selectinload(ValidationBatchModel.platform_account).selectinload(
                PlatformAccountModel.twilio_phone_numbers
            ),
            selectinload(ValidationBatchModel.platform_account).selectinload(
                PlatformAccountModel.openai_credential
            ),
            selectinload(ValidationBatchModel.platform_account).selectinload(
                PlatformAccountModel.email_sender_profile
            ),
        )

    def _build_scoped_storage_batch_id(self, *, account_id: int, public_batch_id: str) -> str:
        digest = hashlib.sha256(f"{account_id}:{public_batch_id}".encode("utf-8")).hexdigest()[:32]
        return f"acct_{account_id}_{digest}"

    def exists(self, batch_id: str, *, account_id: int | None = None) -> bool:
        if account_id is None:
            return self.get_batch_model(batch_id) is not None
        return self.get_batch_model_for_account(batch_id, account_id) is not None

    def list_batches(
        self,
        *,
        account_id: int,
        limit: int = 20,
        offset: int = 0,
        batch_status: BatchStatus | None = None,
    ) -> list[ValidationBatchResponse]:
        statement = (
            self._base_batch_statement()
            .where(ValidationBatchModel.platform_account_id == account_id)
            .order_by(ValidationBatchModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if batch_status is not None:
            statement = statement.where(ValidationBatchModel.batch_status == batch_status)

        batch_models = self.session.scalars(statement).all()
        return [self.build_batch_response(batch_model) for batch_model in batch_models]

    def list_batch_models_for_account(
        self,
        *,
        account_id: int | None,
        batch_status: BatchStatus | None = None,
        source: str | None = None,
    ) -> list[ValidationBatchModel]:
        statement = self._base_batch_statement().order_by(ValidationBatchModel.created_at.desc())
        if account_id is not None:
            statement = statement.where(ValidationBatchModel.platform_account_id == account_id)
        if source is not None:
            statement = statement.where(ValidationBatchModel.source == source)
        if batch_status is not None:
            statement = statement.where(ValidationBatchModel.batch_status == batch_status)
        return self.session.scalars(statement).all()

    def create_from_snapshot(
        self, snapshot: ValidationBatchResponse
    ) -> ValidationBatchResponse:
        storage_batch_id = snapshot.batch_id
        public_batch_id = None
        if snapshot.account_id is not None:
            public_batch_id = snapshot.batch_id
            storage_batch_id = self._build_scoped_storage_batch_id(
                account_id=snapshot.account_id,
                public_batch_id=snapshot.batch_id,
            )

        batch_model = ValidationBatchModel(
            batch_id=storage_batch_id,
            public_batch_id=public_batch_id,
            platform_account_id=snapshot.account_id,
            api_token_id=snapshot.api_token_id,
            caller_company_name=snapshot.caller_company_name,
            workflow_kind=snapshot.workflow_kind,
            segment_name=snapshot.segment_name,
            callback_phone=snapshot.callback_phone,
            callback_contact_name=snapshot.callback_contact_name,
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
                    email_original=record.email_original,
                    email_normalized=record.email_normalized,
                    official_registry_email=record.official_registry_email,
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
                    email_status=record.email_status,
                    phone_confirmed=record.phone_confirmed,
                    confirmation_source=record.confirmation_source,
                    supplier_phone_belongs_to_company=(record.supplier_validation.phone_belongs_to_company if record.supplier_validation else None),
                    supplier_supplies_segment=(record.supplier_validation.supplies_segment if record.supplier_validation else None),
                    supplier_commercial_interest=(record.supplier_validation.commercial_interest if record.supplier_validation else None),
                    supplier_callback_phone_informed=(record.supplier_validation.callback_phone_informed if record.supplier_validation else None),
                    final_status=record.final_status,
                    observation=record.observation,
                )
            )

        self._apply_batch_state(batch_model)
        self.session.add(batch_model)
        self.session.commit()
        return self.get_snapshot_by_batch_id(snapshot.batch_id, account_id=snapshot.account_id)

    def get_snapshot_by_batch_id(
        self, batch_id: str, *, account_id: int | None = None
    ) -> ValidationBatchResponse | None:
        batch_model = (
            self.get_batch_model_for_account(batch_id, account_id)
            if account_id is not None
            else self.get_batch_model_for_public_lookup(batch_id)
        )
        if batch_model is None:
            return None
        return self.build_batch_response(batch_model)

    def get_batch_model(self, batch_id: str) -> ValidationBatchModel | None:
        statement = self._base_batch_statement().where(ValidationBatchModel.batch_id == batch_id)
        return self.session.scalars(statement).first()

    def get_batch_model_for_public_lookup(self, batch_id: str) -> ValidationBatchModel | None:
        exact_match = self.get_batch_model(batch_id)
        if exact_match is not None:
            return exact_match

        statement = (
            self._base_batch_statement()
            .where(ValidationBatchModel.public_batch_id == batch_id)
            .order_by(ValidationBatchModel.created_at.desc())
        )
        return self.session.scalars(statement).first()

    def get_batch_model_for_account(
        self, batch_id: str, account_id: int
    ) -> ValidationBatchModel | None:
        exact_statement = self._base_batch_statement().where(
            ValidationBatchModel.batch_id == batch_id,
            ValidationBatchModel.platform_account_id == account_id,
        )
        exact_match = self.session.scalars(exact_statement).first()
        if exact_match is not None:
            return exact_match

        public_statement = self._base_batch_statement().where(
            ValidationBatchModel.public_batch_id == batch_id,
            ValidationBatchModel.platform_account_id == account_id,
        )
        return self.session.scalars(public_statement).first()

    def get_record_model(
        self, batch_id: str, external_id: str, *, account_id: int | None = None
    ) -> ValidationRecordModel | None:
        statement = (
            select(ValidationRecordModel)
            .options(
                selectinload(ValidationRecordModel.call_attempts),
                selectinload(ValidationRecordModel.whatsapp_messages),
                selectinload(ValidationRecordModel.email_messages),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.records
                ).selectinload(ValidationRecordModel.call_attempts),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.records
                ).selectinload(ValidationRecordModel.whatsapp_messages),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.records
                ).selectinload(ValidationRecordModel.email_messages),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.platform_account
                ).selectinload(PlatformAccountModel.twilio_credential),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.platform_account
                ).selectinload(PlatformAccountModel.twilio_phone_numbers),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.platform_account
                ).selectinload(PlatformAccountModel.openai_credential),
                selectinload(ValidationRecordModel.batch).selectinload(
                    ValidationBatchModel.platform_account
                ).selectinload(PlatformAccountModel.email_sender_profile),
            )
            .join(ValidationRecordModel.batch)
            .where(ValidationRecordModel.external_id == external_id)
        )

        if account_id is not None:
            statement = statement.where(
                ValidationBatchModel.platform_account_id == account_id,
                or_(
                    ValidationBatchModel.public_batch_id == batch_id,
                    ValidationBatchModel.batch_id == batch_id,
                ),
            )
        else:
            statement = statement.where(ValidationBatchModel.batch_id == batch_id)

        return self.session.scalars(statement).first()

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
            batch_id=batch_model.public_batch_id or batch_model.batch_id,
            account_id=batch_model.platform_account_id,
            api_token_id=batch_model.api_token_id,
            caller_company_name=batch_model.caller_company_name,
            workflow_kind=batch_model.workflow_kind,
            segment_name=batch_model.segment_name,
            callback_phone=batch_model.callback_phone,
            callback_contact_name=batch_model.callback_contact_name,
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
        call_attempts = [
            self._build_call_attempt_response(attempt)
            for attempt in record.call_attempts
        ]
        last_attempt = record.call_attempts[-1] if record.call_attempts else None
        confirmed_attempt = next(
            (attempt for attempt in reversed(record.call_attempts) if attempt.result == CallResult.CONFIRMED),
            None,
        )
        registry_attempt = next(
            (
                attempt
                for attempt in reversed(record.call_attempts)
                if attempt.phone_source == CallPhoneSource.OFFICIAL_COMPANY_REGISTRY
            ),
            None,
        )
        last_email = record.email_messages[-1] if record.email_messages else None
        customer_transcript, assistant_transcript = _split_transcript_summary(
            record.transcript_summary
        )
        attempted_phones = _deduplicate_preserving_order(
            [
                attempt.phone_dialed or ""
                for attempt in record.call_attempts
            ]
        )
        supplier_validation = self._build_supplier_validation_response(record)
        is_supplier_validation = (
            getattr(record.batch, "workflow_kind", "cadastral_validation")
            == "supplier_validation"
        )
        official_registry_checked = (
            False
            if is_supplier_validation
            else (
                registry_attempt is not None
                or record.business_status in {
                    BusinessStatus.READY_FOR_RETRY_CALL,
                    BusinessStatus.REJECTED_BY_CALL,
                }
            )
        )
        official_registry_retry_found = registry_attempt is not None and not is_supplier_validation
        official_registry_retry_phone = (
            registry_attempt.phone_dialed if official_registry_retry_found else None
        )
        validated_phone = (
            (confirmed_attempt.phone_dialed if confirmed_attempt else None)
            or (
                (
                    last_attempt.phone_dialed
                    if last_attempt is not None
                    else (record.phone_normalized or record.phone_original)
                )
                if supplier_validation is not None
                and supplier_validation.phone_belongs_to_company is True
                else None
            )
        )

        return ValidationRecordResponse(
            external_id=record.external_id,
            client_name=record.client_name,
            cnpj_original=record.cnpj_original,
            cnpj_normalized=record.cnpj_normalized,
            phone_original=record.phone_original,
            phone_normalized=record.phone_normalized,
            phone_type=record.phone_type,
            email_original=record.email_original,
            email_normalized=record.email_normalized,
            official_registry_email=record.official_registry_email,
            fallback_email_used=(last_email.recipient_email if last_email is not None else None),
            cnpj_found=record.cnpj_found,
            phone_valid=record.phone_valid,
            ready_for_contact=record.ready_for_contact,
            technical_status=record.technical_status,
            business_status=record.business_status,
            call_status=record.call_status,
            call_result=record.call_result,
            transcript_summary=record.transcript_summary,
            customer_transcript=customer_transcript,
            assistant_transcript=assistant_transcript,
            sentiment=record.sentiment,
            whatsapp_status=record.whatsapp_status,
            email_status=record.email_status,
            phone_confirmed=record.phone_confirmed,
            confirmation_source=record.confirmation_source,
            validated_phone=validated_phone,
            last_phone_dialed=(
                last_attempt.phone_dialed
                if last_attempt is not None
                else (record.phone_normalized or record.phone_original)
            ),
            last_phone_source=(last_attempt.phone_source if last_attempt is not None else None),
            attempted_phones=attempted_phones,
            attempts_count=len(record.call_attempts),
            official_registry_checked=official_registry_checked,
            official_registry_retry_found=official_registry_retry_found,
            official_registry_retry_phone=official_registry_retry_phone,
            supplier_validation=supplier_validation,
            final_status=record.final_status,
            observation=record.observation,
            call_attempts=call_attempts,
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
            email_history=[
                EmailMessageResponse(
                    provider_message_id=message.provider_message_id,
                    direction=message.direction,
                    recipient_email=message.recipient_email,
                    subject=message.subject,
                    message_body=message.message_body,
                    response_text=message.response_text,
                    status=message.status,
                    sent_at=message.sent_at,
                    responded_at=message.responded_at,
                    observation=message.observation,
                )
                for message in record.email_messages
            ],
        )

    def _build_call_attempt_response(self, attempt) -> CallAttemptResponse:
        customer_transcript, assistant_transcript = _split_transcript_summary(
            attempt.transcript_summary
        )
        return CallAttemptResponse(
            attempt_number=attempt.attempt_number,
            provider_call_id=attempt.provider_call_id,
            phone_dialed=attempt.phone_dialed,
            from_phone_number_used=attempt.from_phone_number_used,
            phone_source=attempt.phone_source,
            status=attempt.status,
            result=attempt.result,
            transcript_summary=attempt.transcript_summary,
            customer_transcript=customer_transcript,
            assistant_transcript=assistant_transcript,
            sentiment=attempt.sentiment,
            duration_seconds=attempt.duration_seconds,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            observation=attempt.observation,
        )

    def _build_supplier_validation_response(
        self, record: ValidationRecordModel
    ) -> SupplierValidationDetails | None:
        is_supplier_validation = (
            getattr(record.batch, "workflow_kind", "cadastral_validation")
            == "supplier_validation"
        )
        if (
            not is_supplier_validation
            and record.supplier_phone_belongs_to_company is None
            and record.supplier_supplies_segment is None
            and record.supplier_commercial_interest is None
            and record.supplier_callback_phone_informed is None
        ):
            return None

        outcome = None
        if record.supplier_phone_belongs_to_company is False:
            outcome = "wrong_company"
        elif record.supplier_supplies_segment is False:
            outcome = "does_not_supply_segment"
        elif record.supplier_commercial_interest is False:
            outcome = "not_interested"
        elif record.final_status == FinalStatus.VALIDATED:
            outcome = "qualified_supplier"
        elif (
            record.call_status == CallStatus.NOT_ANSWERED
            or record.call_result == CallResult.NOT_ANSWERED
        ):
            outcome = "not_answered"
        elif (
            record.business_status == BusinessStatus.INCONCLUSIVE_CALL
            or record.call_result == CallResult.INCONCLUSIVE
        ):
            outcome = "inconclusive"

        return SupplierValidationDetails(
            segment_name=getattr(record.batch, "segment_name", None),
            phone_belongs_to_company=record.supplier_phone_belongs_to_company,
            supplies_segment=record.supplier_supplies_segment,
            commercial_interest=record.supplier_commercial_interest,
            callback_phone_informed=(
                record.supplier_callback_phone_informed
                or getattr(record.batch, "callback_phone", None)
            ),
            outcome=outcome,
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

    def _apply_batch_state(self, batch_model: ValidationBatchModel) -> None:
        batch_model.total_records = len(batch_model.records)
        records = [self.build_record_response(record) for record in batch_model.records]
        if not records:
            batch_model.technical_status = TechnicalStatus.COMPLETED
            batch_model.batch_status = BatchStatus.COMPLETED
            batch_model.finished_at = datetime.now(timezone.utc)
            return

        if all(record.final_status != FinalStatus.PROCESSING for record in records):
            batch_model.technical_status = TechnicalStatus.COMPLETED
            batch_model.batch_status = BatchStatus.COMPLETED
            batch_model.finished_at = datetime.now(timezone.utc)
        else:
            batch_model.technical_status = TechnicalStatus.PROCESSING
            batch_model.batch_status = BatchStatus.PROCESSING
            batch_model.finished_at = None
