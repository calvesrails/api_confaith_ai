from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..domain.statuses import (
    BusinessStatus,
    CallResult,
    CallStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)


class ValidationRecordResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    external_id: str
    supplier_name: str
    cnpj_original: str
    cnpj_normalized: str | None = None
    phone_original: str
    phone_normalized: str | None = None
    phone_type: str | None = None
    cnpj_found: bool
    phone_valid: bool
    ready_for_contact: bool
    technical_status: TechnicalStatus
    business_status: BusinessStatus
    call_status: CallStatus
    call_result: CallResult
    transcript_summary: str | None = None
    sentiment: str | None = None
    whatsapp_status: WhatsAppStatus
    phone_confirmed: bool
    confirmation_source: str | None = None
    final_status: FinalStatus
    observation: str | None = None


class ValidationBatchSummary(BaseModel):
    ready_for_call: int = 0
    validation_failed: int = 0
    invalid_phone: int = 0
    cnpj_not_found: int = 0
    processing: int = 0


class ValidationBatchResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    batch_id: str
    source: str
    processed_at: datetime
    technical_status: TechnicalStatus
    total_records: int
    summary: ValidationBatchSummary
    records: list[ValidationRecordResponse]
