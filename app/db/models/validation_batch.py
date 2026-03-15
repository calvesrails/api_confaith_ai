from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import BatchStatus, TechnicalStatus
from ..base import Base

if TYPE_CHECKING:
    from .validation_record import ValidationRecordModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationBatchModel(Base):
    __tablename__ = "validation_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(40))
    batch_status: Mapped[BatchStatus] = mapped_column(
        SqlEnum(BatchStatus, native_enum=False)
    )
    technical_status: Mapped[TechnicalStatus] = mapped_column(
        SqlEnum(TechnicalStatus, native_enum=False)
    )
    total_records: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    records: Mapped[list[ValidationRecordModel]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ValidationRecordModel.id",
    )
