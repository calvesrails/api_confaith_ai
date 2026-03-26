from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.statuses import BatchStatus, TechnicalStatus
from ..base import Base
from ..enum_types import FlexibleEnum

if TYPE_CHECKING:
    from .api_token import ApiTokenModel
    from .platform_account import PlatformAccountModel
    from .validation_record import ValidationRecordModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationBatchModel(Base):
    __tablename__ = "validation_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    public_batch_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    platform_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    api_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    caller_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workflow_kind: Mapped[str] = mapped_column(String(40), default="cadastral_validation")
    segment_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    callback_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    callback_contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(40))
    batch_status: Mapped[BatchStatus] = mapped_column(FlexibleEnum(BatchStatus))
    technical_status: Mapped[TechnicalStatus] = mapped_column(FlexibleEnum(TechnicalStatus))
    total_records: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records: Mapped[list[ValidationRecordModel]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ValidationRecordModel.id",
    )
    platform_account: Mapped[PlatformAccountModel | None] = relationship(back_populates="validation_batches")
    api_token: Mapped[ApiTokenModel | None] = relationship(back_populates="validation_batches")
