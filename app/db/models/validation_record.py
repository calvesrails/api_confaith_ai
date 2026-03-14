from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import (
    BusinessStatus,
    CallResult,
    CallStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)
from ..base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationRecordModel(Base):
    __tablename__ = "validation_records"
    __table_args__ = (
        UniqueConstraint(
            "validation_batch_id",
            "external_id",
            name="uq_validation_record_batch_external",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_batch_id: Mapped[int] = mapped_column(
        ForeignKey("validation_batches.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(120))
    supplier_name: Mapped[str] = mapped_column(String(255))
    cnpj_original: Mapped[str] = mapped_column(String(32))
    cnpj_normalized: Mapped[str | None] = mapped_column(String(14), nullable=True)
    phone_original: Mapped[str] = mapped_column(String(32))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cnpj_found: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    ready_for_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    technical_status: Mapped[TechnicalStatus] = mapped_column(
        SqlEnum(TechnicalStatus, native_enum=False)
    )
    business_status: Mapped[BusinessStatus] = mapped_column(
        SqlEnum(BusinessStatus, native_enum=False)
    )
    call_status: Mapped[CallStatus] = mapped_column(
        SqlEnum(CallStatus, native_enum=False)
    )
    call_result: Mapped[CallResult] = mapped_column(
        SqlEnum(CallResult, native_enum=False)
    )
    transcript_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    whatsapp_status: Mapped[WhatsAppStatus] = mapped_column(
        SqlEnum(WhatsAppStatus, native_enum=False)
    )
    phone_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    final_status: Mapped[FinalStatus] = mapped_column(
        SqlEnum(FinalStatus, native_enum=False)
    )
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_attempts: Mapped[list] = mapped_column(JSON, default=list)
    whatsapp_history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )
    batch: Mapped["ValidationBatchModel"] = relationship(back_populates="records")
