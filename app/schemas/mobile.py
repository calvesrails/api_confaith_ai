from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..domain.statuses import (
    BusinessStatus,
    CallPhoneSource,
    CallResult,
    CallStatus,
    FinalStatus,
)


class MobilePeriod(str, Enum):
    LAST_24_HOURS = "24h"
    WEEK = "week"
    MONTH = "month"


class MobileDashboardSummary(BaseModel):
    total_batches: int = 0
    completed_batches: int = 0
    processing_batches: int = 0
    total_records: int = 0
    validated_phones: int = 0
    confirmed_numbers: int = 0
    not_confirmed_numbers: int = 0
    not_answered_numbers: int = 0
    average_call_duration_seconds: float = 0.0
    average_call_cost_estimate_brl: float = 0.0
    total_call_attempts: int = 0


class MobileDashboardRecordItem(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    batch_id: str
    external_id: str
    client_name: str
    phone_original: str
    phone_normalized: str | None = None
    validated_phone: str | None = None
    last_phone_dialed: str | None = None
    call_status: CallStatus
    call_result: CallResult
    business_status: BusinessStatus
    final_status: FinalStatus
    phone_confirmed: bool
    confirmation_source: str | None = None
    observation: str | None = None


class MobileDashboardResponse(BaseModel):
    period: MobilePeriod
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    summary: MobileDashboardSummary
    confirmed_records: list[MobileDashboardRecordItem] = Field(default_factory=list)
    not_confirmed_records: list[MobileDashboardRecordItem] = Field(default_factory=list)
    not_answered_records: list[MobileDashboardRecordItem] = Field(default_factory=list)


class MobileCallItem(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    batch_id: str
    external_id: str
    client_name: str
    phone_original: str
    phone_normalized: str | None = None
    validated_phone: str | None = None
    phone_confirmed: bool
    attempt_number: int
    provider_call_id: str | None = None
    phone_dialed: str | None = None
    from_phone_number_used: str | None = None
    phone_source: CallPhoneSource
    status: CallStatus
    result: CallResult
    duration_seconds: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    transcript_summary: str | None = None
    customer_transcript: str | None = None
    assistant_transcript: str | None = None
    observation: str | None = None


class MobileCallListResponse(BaseModel):
    period: MobilePeriod
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    total: int
    limit: int
    offset: int
    items: list[MobileCallItem] = Field(default_factory=list)
