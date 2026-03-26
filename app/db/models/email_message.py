from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import EmailStatus
from ..base import Base

if TYPE_CHECKING:
    from .validation_record import ValidationRecordModel



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EmailMessageModel(Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_record_id: Mapped[int] = mapped_column(
        ForeignKey("validation_records.id", ondelete="CASCADE"),
        index=True,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(String(20))
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EmailStatus] = mapped_column(
        SqlEnum(EmailStatus, native_enum=False)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )
    record: Mapped[ValidationRecordModel] = relationship(back_populates="email_messages")
