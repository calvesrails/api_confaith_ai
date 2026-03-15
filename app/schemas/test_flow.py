from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LocalCallScenario(str, Enum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    NOT_ANSWERED = "not_answered"


class LocalTechnicalStatus(str, Enum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    CALL_SIMULATED = "call_simulated"
    WHATSAPP_SENT = "whatsapp_sent"
    WEBHOOK_RECEIVED = "webhook_received"
    COMPLETED = "completed"
    ERROR = "error"


class LocalBusinessStatus(str, Enum):
    CONFIRMED_BY_CALL = "confirmed_by_call"
    FAILED_CALL = "failed_call"
    INCONCLUSIVE_CALL = "inconclusive_call"
    NOT_ANSWERED = "not_answered"
    WAITING_WHATSAPP_REPLY = "waiting_whatsapp_reply"
    CONFIRMED_BY_WHATSAPP = "confirmed_by_whatsapp"
    REJECTED_BY_WHATSAPP = "rejected_by_whatsapp"


class LocalCallStatus(str, Enum):
    ANSWERED = "answered"
    FAILED = "failed"
    NOT_ANSWERED = "not_answered"


class LocalCallResult(str, Enum):
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"
    INCONCLUSIVE = "inconclusive"
    NOT_ANSWERED = "not_answered"


class LocalValidationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    client_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices(
            "client_name",
            "supplier_name",
            "nome_cliente",
            "nome_fornecedor",
        ),
    )
    cnpj: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    call_scenario: LocalCallScenario
    fallback_message: str = Field(min_length=1)


class ManualWhatsAppSendRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    phone: str = Field(min_length=1)
    message: str = Field(min_length=1)


class CallSimulationResult(BaseModel):
    call_status: LocalCallStatus
    call_result: LocalCallResult
    business_status: LocalBusinessStatus
    should_send_whatsapp: bool


class WhatsAppSendResult(BaseModel):
    meta_http_status: int
    success: bool
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None = None
    meta_message_id: str | None = None
    error_message: str | None = None


class StoredWhatsAppSend(WhatsAppSendResult):
    origin: str
    phone_normalized: str
    request_id: str | None = None
    client_name: str | None = None
    created_at: datetime


class LocalTestFlowResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    request_id: str
    client_name: str
    cnpj_original: str
    cnpj_normalized: str | None = None
    phone_original: str
    phone_normalized: str | None = None
    call_scenario: LocalCallScenario
    call_status: LocalCallStatus | None = None
    call_result: LocalCallResult | None = None
    call_business_status: LocalBusinessStatus | None = None
    should_send_whatsapp: bool
    fallback_message: str
    technical_status: LocalTechnicalStatus
    business_status: LocalBusinessStatus | None = None
    flow_finished: bool
    whatsapp: WhatsAppSendResult | None = None
    last_user_reply: str | None = None
    last_delivery_status: str | None = None
    meta_message_id: str | None = None
    observation: str | None = None
    created_at: datetime
    updated_at: datetime


class FlowLogEntry(BaseModel):
    timestamp: datetime
    stage: str
    message: str
    data: dict[str, Any] | None = None


class WebhookEventSummary(BaseModel):
    event_type: str
    phone: str | None = None
    message_id: str | None = None
    text: str | None = None
    status: str | None = None
    raw: dict[str, Any] | None = None


class LocalTestStateResponse(BaseModel):
    recent_requests: list[LocalTestFlowResponse]
    recent_whatsapp_sends: list[StoredWhatsAppSend]
    logs: list[FlowLogEntry]
    last_webhook_payload: dict[str, Any] | None = None
    last_webhook_event: WebhookEventSummary | None = None


class ClearStateResponse(BaseModel):
    message: str


class WebhookReceiveResponse(BaseModel):
    received: bool
    events_processed: int
