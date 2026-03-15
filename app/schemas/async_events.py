from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..domain.statuses import CallResult, CallStatus, WhatsAppStatus


class CallEventRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider_call_id: str | None = None
    call_status: CallStatus
    call_result: CallResult
    transcript_summary: str | None = None
    sentiment: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    observation: str | None = None
    happened_at: datetime | None = None


class WhatsAppEventRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider_message_id: str | None = None
    status: WhatsAppStatus
    direction: str = "inbound"
    message_body: str | None = None
    response_text: str | None = None
    observation: str | None = None
    happened_at: datetime | None = None
