from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .platform_account import PlatformAccountModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OpenAICredentialModel(Base):
    __tablename__ = 'openai_credentials'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey('platform_accounts.id', ondelete='CASCADE'),
        unique=True,
        index=True,
    )
    api_key: Mapped[str] = mapped_column(Text)
    realtime_model: Mapped[str] = mapped_column(String(120), default='gpt-realtime-1.5')
    realtime_voice: Mapped[str] = mapped_column(String(60), default='cedar')
    realtime_output_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    realtime_style_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )

    account: Mapped[PlatformAccountModel] = relationship(back_populates='openai_credential')
