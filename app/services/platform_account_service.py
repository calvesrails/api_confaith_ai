from __future__ import annotations

from dataclasses import dataclass

from ..db.models import ApiTokenModel, PlatformAccountModel
from ..repositories.platform_account_repository import PlatformAccountRepository
from ..schemas.platform_accounts import (
    ApiTokenCreateRequest,
    ApiTokenCreateResponse,
    CompanyProfileRequest,
    EmailProviderRequest,
    OpenAIProviderRequest,
    PlatformAccountCreateRequest,
    PlatformAccountResponse,
    TwilioProviderRequest,
)
from .errors import (
    PlatformAccountNotFoundError,
    PlatformAuthenticationError,
    PlatformConfigurationError,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedApiTokenContext:
    account_id: int
    api_token_id: int
    account: PlatformAccountModel
    api_token: ApiTokenModel


class PlatformAccountService:
    def __init__(self, repository: PlatformAccountRepository) -> None:
        self.repository = repository

    def create_account(
        self,
        payload: PlatformAccountCreateRequest,
    ) -> PlatformAccountResponse:
        account = self.repository.create_or_update_account(payload)
        return self.repository.build_account_response(account)

    def get_account(self, account_id: int) -> PlatformAccountResponse:
        account = self.repository.get_account_by_id(account_id)
        if account is None:
            raise PlatformAccountNotFoundError(account_id)
        return self.repository.build_account_response(account)

    def get_latest_account(self) -> PlatformAccountResponse | None:
        account = self.repository.get_latest_account()
        if account is None:
            return None
        return self.repository.build_account_response(account)

    def update_company_profile(
        self,
        account_id: int,
        payload: CompanyProfileRequest,
    ) -> PlatformAccountResponse:
        account = self._get_account_model(account_id)
        updated = self.repository.save_company_profile(account, payload)
        return self.repository.build_account_response(updated)

    def update_twilio_provider(
        self,
        account_id: int,
        payload: TwilioProviderRequest,
    ) -> PlatformAccountResponse:
        account = self._get_account_model(account_id)
        updated = self.repository.save_twilio_provider(account, payload)
        return self.repository.build_account_response(updated)

    def update_openai_provider(
        self,
        account_id: int,
        payload: OpenAIProviderRequest,
    ) -> PlatformAccountResponse:
        account = self._get_account_model(account_id)
        updated = self.repository.save_openai_provider(account, payload)
        return self.repository.build_account_response(updated)

    def update_email_provider(
        self,
        account_id: int,
        payload: EmailProviderRequest,
    ) -> PlatformAccountResponse:
        account = self._get_account_model(account_id)
        updated = self.repository.save_email_provider(account, payload)
        return self.repository.build_account_response(updated)

    def create_api_token(
        self,
        account_id: int,
        payload: ApiTokenCreateRequest,
    ) -> ApiTokenCreateResponse:
        account = self._get_account_model(account_id)
        return self.repository.create_api_token(
            account,
            name=payload.name,
            expires_at=payload.expires_at,
        )

    def authenticate_authorization_header(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedApiTokenContext:
        raw_token = self._extract_bearer_token(authorization_header)
        token = self.repository.authenticate_api_token(raw_token)
        if token is None or token.account is None:
            raise PlatformAuthenticationError()
        return AuthenticatedApiTokenContext(
            account_id=token.account.id,
            api_token_id=token.id,
            account=token.account,
            api_token=token,
        )

    def authenticate_optional_authorization_header(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedApiTokenContext | None:
        if not authorization_header:
            return None
        return self.authenticate_authorization_header(authorization_header)

    def ensure_account_ready_for_validations(
        self,
        account: PlatformAccountModel,
    ) -> None:
        errors: list[str] = []

        if not account.company_name:
            errors.append("company_name nao configurado")
        if account.twilio_credential is None:
            errors.append("credenciais Twilio nao configuradas")
        if not any(phone.is_active for phone in account.twilio_phone_numbers):
            errors.append("nenhum numero Twilio ativo configurado")
        if account.openai_credential is None:
            errors.append("credenciais OpenAI nao configuradas")

        if errors:
            raise PlatformConfigurationError(
                "Conta sem configuracao minima para processar lotes: " + "; ".join(errors)
            )

    def _get_account_model(self, account_id: int) -> PlatformAccountModel:
        account = self.repository.get_account_by_id(account_id)
        if account is None:
            raise PlatformAccountNotFoundError(account_id)
        return account

    def _extract_bearer_token(self, authorization_header: str | None) -> str:
        if not authorization_header:
            raise PlatformAuthenticationError("Header Authorization ausente.")

        scheme, _, raw_token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not raw_token.strip():
            raise PlatformAuthenticationError("Header Authorization invalido. Use Bearer <token>.")
        return raw_token.strip()
