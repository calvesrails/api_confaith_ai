from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .platform_account import PlatformAccountModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TwilioCredentialModel(Base):
    __tablename__ = "twilio_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    account_sid: Mapped[str] = mapped_column(String(64))
    auth_token: Mapped[str] = mapped_column(String(255))
    webhook_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )

    account: Mapped[PlatformAccountModel] = relationship(back_populates="twilio_credential")
