from pydantic import BaseModel


class EmailSendResult(BaseModel):
    success: bool
    provider_message_id: str | None = None
    subject: str
    message_body: str
    error_message: str | None = None
