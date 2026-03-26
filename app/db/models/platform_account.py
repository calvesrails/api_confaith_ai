from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .api_token import ApiTokenModel
    from .email_sender_profile import EmailSenderProfileModel
    from .openai_credential import OpenAICredentialModel
    from .twilio_credential import TwilioCredentialModel
    from .twilio_phone_number import TwilioPhoneNumberModel
    from .validation_batch import ValidationBatchModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlatformAccountModel(Base):
    __tablename__ = "platform_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_account_id: Mapped[str | None] = mapped_column(
        String(120),
        unique=True,
        nullable=True,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255))
    spoken_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
    )

    api_tokens: Mapped[list[ApiTokenModel]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="ApiTokenModel.id",
    )
    twilio_credential: Mapped[TwilioCredentialModel | None] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    twilio_phone_numbers: Mapped[list[TwilioPhoneNumberModel]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="TwilioPhoneNumberModel.id",
    )
    openai_credential: Mapped[OpenAICredentialModel | None] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    email_sender_profile: Mapped[EmailSenderProfileModel | None] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    validation_batches: Mapped[list[ValidationBatchModel]] = relationship(
        back_populates="platform_account",
    )
