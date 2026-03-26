from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .platform_account import PlatformAccountModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TwilioPhoneNumberModel(Base):
    __tablename__ = "twilio_phone_numbers"
    __table_args__ = (
        UniqueConstraint(
            "platform_account_id",
            "phone_number",
            name="uq_twilio_phone_number_account_phone",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(String(20))
    friendly_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )

    account: Mapped[PlatformAccountModel] = relationship(back_populates="twilio_phone_numbers")
