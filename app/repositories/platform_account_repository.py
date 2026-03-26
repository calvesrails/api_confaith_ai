from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db.models import (
    ApiTokenModel,
    EmailSenderProfileModel,
    OpenAICredentialModel,
    PlatformAccountModel,
    TwilioCredentialModel,
    TwilioPhoneNumberModel,
)
from ..schemas.platform_accounts import (
    ApiTokenCreateResponse,
    CompanyProfileRequest,
    EmailProviderRequest,
    EmailProviderResponse,
    OpenAIProviderRequest,
    OpenAIProviderResponse,
    PlatformAccountCreateRequest,
    PlatformAccountResponse,
    TwilioPhoneNumberResponse,
    TwilioProviderRequest,
    TwilioProviderResponse,
)
from ..services.phone import normalize_phone
from ..utils.security import generate_api_token, hash_api_token, mask_secret


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PlatformAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_account_by_id(self, account_id: int) -> PlatformAccountModel | None:
        statement = (
            select(PlatformAccountModel)
            .options(*self._account_load_options())
            .where(PlatformAccountModel.id == account_id)
        )
        return self.session.scalars(statement).first()

    def get_account_by_external_account_id(
        self,
        external_account_id: str,
    ) -> PlatformAccountModel | None:
        statement = (
            select(PlatformAccountModel)
            .options(*self._account_load_options())
            .where(PlatformAccountModel.external_account_id == external_account_id)
        )
        return self.session.scalars(statement).first()

    def create_or_update_account(
        self,
        payload: PlatformAccountCreateRequest,
    ) -> PlatformAccountModel:
        account = None
        if payload.external_account_id:
            account = self.get_account_by_external_account_id(payload.external_account_id)

        if account is None:
            account = PlatformAccountModel(
                external_account_id=payload.external_account_id,
                company_name=payload.company_name,
                spoken_company_name=payload.spoken_company_name,
                owner_name=payload.owner_name,
                owner_email=payload.owner_email,
            )
            self.session.add(account)
        else:
            account.company_name = payload.company_name
            account.spoken_company_name = payload.spoken_company_name
            account.owner_name = payload.owner_name
            account.owner_email = payload.owner_email

        self.session.commit()
        assert account.id is not None
        return self.get_account_by_id(account.id) or account

    def save_company_profile(
        self,
        account: PlatformAccountModel,
        payload: CompanyProfileRequest,
    ) -> PlatformAccountModel:
        account.company_name = payload.company_name
        account.spoken_company_name = payload.spoken_company_name
        account.owner_name = payload.owner_name
        account.owner_email = payload.owner_email
        self.session.add(account)
        self.session.commit()
        return self.get_account_by_id(account.id) or account

    def save_twilio_provider(
        self,
        account: PlatformAccountModel,
        payload: TwilioProviderRequest,
    ) -> PlatformAccountModel:
        credential = account.twilio_credential
        if credential is None:
            credential = TwilioCredentialModel(platform_account_id=account.id)
            account.twilio_credential = credential

        credential.account_sid = payload.account_sid
        credential.auth_token = payload.auth_token
        credential.webhook_base_url = payload.webhook_base_url

        new_phone_numbers: list[TwilioPhoneNumberModel] = []
        for phone in payload.phone_numbers:
            normalized_phone = normalize_phone(phone.phone_number) or phone.phone_number
            new_phone_numbers.append(
                TwilioPhoneNumberModel(
                    phone_number=normalized_phone,
                    friendly_name=phone.friendly_name,
                    is_active=phone.is_active,
                    max_concurrent_calls=phone.max_concurrent_calls,
                )
            )

        account.twilio_phone_numbers = new_phone_numbers
        self.session.add(account)
        self.session.commit()
        return self.get_account_by_id(account.id) or account

    def save_openai_provider(
        self,
        account: PlatformAccountModel,
        payload: OpenAIProviderRequest,
    ) -> PlatformAccountModel:
        credential = account.openai_credential
        if credential is None:
            credential = OpenAICredentialModel(platform_account_id=account.id)
            account.openai_credential = credential

        credential.api_key = payload.api_key
        credential.realtime_model = payload.realtime_model
        credential.realtime_voice = payload.realtime_voice
        credential.realtime_output_speed = payload.realtime_output_speed
        credential.realtime_style_instructions = payload.realtime_style_instructions

        self.session.add(account)
        self.session.commit()
        return self.get_account_by_id(account.id) or account

    def save_email_provider(
        self,
        account: PlatformAccountModel,
        payload: EmailProviderRequest,
    ) -> PlatformAccountModel:
        profile = account.email_sender_profile
        if profile is None:
            profile = EmailSenderProfileModel(platform_account_id=account.id)
            account.email_sender_profile = profile

        profile.enabled = payload.enabled
        profile.smtp_host = payload.smtp_host
        profile.smtp_port = payload.smtp_port
        profile.smtp_username = payload.smtp_username
        profile.smtp_password = payload.smtp_password
        profile.smtp_use_tls = payload.smtp_use_tls
        profile.from_address = payload.from_address
        profile.from_name = payload.from_name

        self.session.add(account)
        self.session.commit()
        return self.get_account_by_id(account.id) or account

    def create_api_token(
        self,
        account: PlatformAccountModel,
        *,
        name: str,
        expires_at: datetime | None,
    ) -> ApiTokenCreateResponse:
        generated_token = generate_api_token()
        token_model = ApiTokenModel(
            platform_account_id=account.id,
            name=name,
            token_prefix=generated_token.token_prefix,
            token_hash=generated_token.token_hash,
            expires_at=_ensure_utc(expires_at),
        )
        self.session.add(token_model)
        self.session.commit()
        self.session.refresh(token_model)
        return ApiTokenCreateResponse(
            account_id=account.id,
            token_id=token_model.id,
            name=token_model.name,
            token_prefix=token_model.token_prefix,
            raw_token=generated_token.raw_token,
            created_at=token_model.created_at,
            expires_at=_ensure_utc(token_model.expires_at),
        )

    def authenticate_api_token(self, raw_token: str) -> ApiTokenModel | None:
        now = _utc_now()
        statement = (
            select(ApiTokenModel)
            .options(*self._token_load_options())
            .where(ApiTokenModel.token_hash == hash_api_token(raw_token))
            .where(ApiTokenModel.revoked_at.is_(None))
        )
        token_model = self.session.scalars(statement).first()
        if token_model is None:
            return None
        expires_at = _ensure_utc(token_model.expires_at)
        if expires_at is not None and expires_at <= now:
            return None

        token_model.last_used_at = now
        self.session.add(token_model)
        self.session.commit()
        return self.session.get(ApiTokenModel, token_model.id, options=self._token_load_options())

    def build_account_response(self, account: PlatformAccountModel) -> PlatformAccountResponse:
        active_tokens = self._count_active_tokens(account)
        caller_company_name = account.spoken_company_name or account.company_name
        return PlatformAccountResponse(
            id=account.id,
            external_account_id=account.external_account_id,
            company_name=account.company_name,
            spoken_company_name=account.spoken_company_name,
            owner_name=account.owner_name,
            owner_email=account.owner_email,
            status=account.status,
            caller_company_name=caller_company_name,
            active_api_tokens=active_tokens,
            twilio=self._build_twilio_response(account),
            openai=self._build_openai_response(account),
            email=self._build_email_response(account),
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    def _build_twilio_response(self, account: PlatformAccountModel) -> TwilioProviderResponse:
        credential = account.twilio_credential
        phone_numbers = [
            TwilioPhoneNumberResponse(
                id=phone.id,
                phone_number=phone.phone_number,
                friendly_name=phone.friendly_name,
                is_active=phone.is_active,
                max_concurrent_calls=phone.max_concurrent_calls,
            )
            for phone in account.twilio_phone_numbers
        ]
        return TwilioProviderResponse(
            configured=credential is not None and bool(account.twilio_phone_numbers),
            account_sid_masked=mask_secret(credential.account_sid) if credential else None,
            webhook_base_url=credential.webhook_base_url if credential else None,
            active_phone_numbers=sum(phone.is_active for phone in account.twilio_phone_numbers),
            phone_numbers=phone_numbers,
        )

    def _build_openai_response(self, account: PlatformAccountModel) -> OpenAIProviderResponse:
        credential = account.openai_credential
        return OpenAIProviderResponse(
            configured=credential is not None,
            api_key_masked=mask_secret(credential.api_key) if credential else None,
            realtime_model=credential.realtime_model if credential else None,
            realtime_voice=credential.realtime_voice if credential else None,
            realtime_output_speed=credential.realtime_output_speed if credential else None,
            has_style_instructions=bool(credential and credential.realtime_style_instructions),
        )

    def _build_email_response(self, account: PlatformAccountModel) -> EmailProviderResponse:
        profile = account.email_sender_profile
        return EmailProviderResponse(
            configured=bool(profile and profile.enabled and profile.smtp_host and profile.from_address),
            enabled=bool(profile.enabled) if profile else False,
            smtp_host=profile.smtp_host if profile else None,
            from_address=profile.from_address if profile else None,
            from_name=profile.from_name if profile else None,
        )

    def _count_active_tokens(self, account: PlatformAccountModel) -> int:
        now = _utc_now()
        return sum(
            token.revoked_at is None and (token.expires_at is None or token.expires_at > now)
            for token in account.api_tokens
        )

    def _account_load_options(self) -> list[Any]:
        return [
            selectinload(PlatformAccountModel.api_tokens),
            selectinload(PlatformAccountModel.twilio_credential),
            selectinload(PlatformAccountModel.twilio_phone_numbers),
            selectinload(PlatformAccountModel.openai_credential),
            selectinload(PlatformAccountModel.email_sender_profile),
        ]

    def _token_load_options(self) -> list[Any]:
        return [
            selectinload(ApiTokenModel.account).selectinload(PlatformAccountModel.api_tokens),
            selectinload(ApiTokenModel.account).selectinload(PlatformAccountModel.twilio_credential),
            selectinload(ApiTokenModel.account).selectinload(PlatformAccountModel.twilio_phone_numbers),
            selectinload(ApiTokenModel.account).selectinload(PlatformAccountModel.openai_credential),
            selectinload(ApiTokenModel.account).selectinload(PlatformAccountModel.email_sender_profile),
        ]
