from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import WhatsAppStatus
from ..base import Base
from ..enum_types import FlexibleEnum

if TYPE_CHECKING:
    from .validation_record import ValidationRecordModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppMessageModel(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_record_id: Mapped[int] = mapped_column(
        ForeignKey("validation_records.id", ondelete="CASCADE"),
        index=True,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    direction: Mapped[str] = mapped_column(String(20))
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WhatsAppStatus] = mapped_column(
        FlexibleEnum(WhatsAppStatus)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    record: Mapped[ValidationRecordModel] = relationship(
        back_populates="whatsapp_messages"
    )
