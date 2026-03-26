from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import CallPhoneSource, CallResult, CallStatus
from ..base import Base
from ..enum_types import FlexibleEnum

if TYPE_CHECKING:
    from .validation_record import ValidationRecordModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CallAttemptModel(Base):
    __tablename__ = "call_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_record_id: Mapped[int] = mapped_column(
        ForeignKey("validation_records.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_dialed: Mapped[str | None] = mapped_column(String(20), nullable=True)
    from_phone_number_used: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone_source: Mapped[CallPhoneSource] = mapped_column(
        FlexibleEnum(CallPhoneSource),
        default=CallPhoneSource.PAYLOAD_PHONE,
    )
    status: Mapped[CallStatus] = mapped_column(
        FlexibleEnum(CallStatus)
    )
    result: Mapped[CallResult] = mapped_column(
        FlexibleEnum(CallResult)
    )
    transcript_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    record: Mapped[ValidationRecordModel] = relationship(back_populates="call_attempts")
