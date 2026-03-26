from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import (
    BusinessStatus,
    CallResult,
    CallStatus,
    EmailStatus,
    FinalStatus,
    TechnicalStatus,
    WhatsAppStatus,
)
from ..base import Base
from ..enum_types import FlexibleEnum

if TYPE_CHECKING:
    from .call_attempt import CallAttemptModel
    from .email_message import EmailMessageModel
    from .validation_batch import ValidationBatchModel
    from .whatsapp_message import WhatsAppMessageModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationRecordModel(Base):
    __tablename__ = "validation_records"
    __table_args__ = (
        UniqueConstraint("validation_batch_id", "external_id", name="uq_validation_record_batch_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_batch_id: Mapped[int] = mapped_column(ForeignKey("validation_batches.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    client_name: Mapped[str] = mapped_column("supplier_name", String(255))
    cnpj_original: Mapped[str] = mapped_column(String(32))
    cnpj_normalized: Mapped[str | None] = mapped_column(String(14), nullable=True)
    phone_original: Mapped[str] = mapped_column(String(32))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_original: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    official_registry_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    cnpj_found: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    ready_for_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    technical_status: Mapped[TechnicalStatus] = mapped_column(FlexibleEnum(TechnicalStatus))
    business_status: Mapped[BusinessStatus] = mapped_column(FlexibleEnum(BusinessStatus))
    call_status: Mapped[CallStatus] = mapped_column(FlexibleEnum(CallStatus))
    call_result: Mapped[CallResult] = mapped_column(FlexibleEnum(CallResult))
    transcript_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    whatsapp_status: Mapped[WhatsAppStatus] = mapped_column(FlexibleEnum(WhatsAppStatus))
    email_status: Mapped[EmailStatus] = mapped_column(FlexibleEnum(EmailStatus), default=EmailStatus.NOT_REQUIRED)
    phone_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supplier_phone_belongs_to_company: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supplier_supplies_segment: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supplier_commercial_interest: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supplier_callback_phone_informed: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_status: Mapped[FinalStatus] = mapped_column(FlexibleEnum(FinalStatus))
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
    batch: Mapped[ValidationBatchModel] = relationship(back_populates="records")
    call_attempts: Mapped[list[CallAttemptModel]] = relationship(back_populates="record", cascade="all, delete-orphan", order_by="CallAttemptModel.attempt_number")
    whatsapp_messages: Mapped[list[WhatsAppMessageModel]] = relationship(back_populates="record", cascade="all, delete-orphan", order_by="WhatsAppMessageModel.created_at")
    email_messages: Mapped[list[EmailMessageModel]] = relationship(back_populates="record", cascade="all, delete-orphan", order_by="EmailMessageModel.created_at")
