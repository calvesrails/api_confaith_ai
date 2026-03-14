from enum import Enum


class TechnicalStatus(str, Enum):
    RECEIVED = "received"
    PAYLOAD_INVALID = "payload_invalid"
    NORMALIZED = "normalized"
    READY_FOR_VALIDATION = "ready_for_validation"
    PROCESSING = "processing"
    COMPLETED = "completed"


class BusinessStatus(str, Enum):
    CNPJ_NOT_FOUND = "cnpj_not_found"
    INVALID_PHONE = "invalid_phone"
    READY_FOR_CALL = "ready_for_call"
    CALL_NOT_ANSWERED = "call_not_answered"
    CALL_ANSWERED = "call_answered"
    CONFIRMED_BY_CALL = "confirmed_by_call"
    REJECTED_BY_CALL = "rejected_by_call"
    INCONCLUSIVE_CALL = "inconclusive_call"
    WHATSAPP_SENT = "whatsapp_sent"
    WAITING_WHATSAPP_REPLY = "waiting_whatsapp_reply"
    CONFIRMED_BY_WHATSAPP = "confirmed_by_whatsapp"
    REJECTED_BY_WHATSAPP = "rejected_by_whatsapp"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"


class CallStatus(str, Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    ANSWERED = "answered"
    NOT_ANSWERED = "not_answered"
    FAILED = "failed"


class CallResult(str, Enum):
    NOT_STARTED = "not_started"
    PENDING_DISPATCH = "pending_dispatch"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class WhatsAppStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    QUEUED = "queued"
    SENT = "sent"
    WAITING_REPLY = "waiting_whatsapp_reply"
    CONFIRMED = "confirmed_by_whatsapp"
    REJECTED = "rejected_by_whatsapp"
    EXPIRED = "expired_without_reply"


class FinalStatus(str, Enum):
    PROCESSING = "processing"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
