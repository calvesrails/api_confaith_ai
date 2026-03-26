from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..domain.statuses import (
    BatchStatus,
    BusinessStatus,
    CallPhoneSource,
    CallResult,
    CallStatus,
    EmailStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)


class SupplierValidationDetails(BaseModel):
    segment_name: str | None = None
    phone_belongs_to_company: bool | None = None
    supplies_segment: bool | None = None
    commercial_interest: bool | None = None
    callback_phone_informed: str | None = None
    outcome: str | None = None


class ValidationRecordResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    external_id: str
    client_name: str
    cnpj_original: str
    cnpj_normalized: str | None = None
    phone_original: str
    phone_normalized: str | None = None
    phone_type: str | None = None
    email_original: str | None = None
    email_normalized: str | None = None
    official_registry_email: str | None = None
    fallback_email_used: str | None = None
    cnpj_found: bool
    phone_valid: bool
    ready_for_contact: bool
    technical_status: TechnicalStatus
    business_status: BusinessStatus
    call_status: CallStatus
    call_result: CallResult
    transcript_summary: str | None = None
    customer_transcript: str | None = None
    assistant_transcript: str | None = None
    sentiment: str | None = None
    whatsapp_status: WhatsAppStatus
    email_status: EmailStatus
    phone_confirmed: bool
    confirmation_source: str | None = None
    validated_phone: str | None = None
    last_phone_dialed: str | None = None
    last_phone_source: CallPhoneSource | None = None
    attempted_phones: list[str] = Field(default_factory=list)
    attempts_count: int = 0
    official_registry_checked: bool = False
    official_registry_retry_found: bool = False
    official_registry_retry_phone: str | None = None
    supplier_validation: SupplierValidationDetails | None = None
    final_status: FinalStatus
    observation: str | None = None
    call_attempts: list[CallAttemptResponse] = Field(default_factory=list)
    whatsapp_history: list[WhatsAppMessageResponse] = Field(default_factory=list)
    email_history: list[EmailMessageResponse] = Field(default_factory=list)


class CallAttemptResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    attempt_number: int
    provider_call_id: str | None = None
    phone_dialed: str | None = None
    from_phone_number_used: str | None = None
    phone_source: CallPhoneSource
    status: CallStatus
    result: CallResult
    transcript_summary: str | None = None
    customer_transcript: str | None = None
    assistant_transcript: str | None = None
    sentiment: str | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    observation: str | None = None


class WhatsAppMessageResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    provider_message_id: str | None = None
    direction: str
    message_body: str | None = None
    response_text: str | None = None
    status: WhatsAppStatus
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    observation: str | None = None


class EmailMessageResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    provider_message_id: str | None = None
    direction: str
    recipient_email: str | None = None
    subject: str | None = None
    message_body: str | None = None
    response_text: str | None = None
    status: EmailStatus
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    observation: str | None = None


class ValidationBatchSummary(BaseModel):
    ready_for_call: int = 0
    ready_for_retry_call: int = 0
    validation_failed: int = 0
    invalid_phone: int = 0
    cnpj_not_found: int = 0
    processing: int = 0
    pending_records: int = 0
    validated_records: int = 0
    failed_records: int = 0
    confirmed_by_call: int = 0
    confirmed_by_whatsapp: int = 0
    waiting_whatsapp_reply: int = 0
    confirmed_by_email: int = 0
    waiting_email_reply: int = 0


class ValidationBatchResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    batch_id: str
    account_id: int | None = None
    api_token_id: int | None = None
    caller_company_name: str | None = None
    workflow_kind: str = "cadastral_validation"
    segment_name: str | None = None
    callback_phone: str | None = None
    callback_contact_name: str | None = None
    source: str
    batch_status: BatchStatus
    processed_at: datetime
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    result_ready: bool
    technical_status: TechnicalStatus
    total_records: int
    summary: ValidationBatchSummary
    records: list[ValidationRecordResponse]
