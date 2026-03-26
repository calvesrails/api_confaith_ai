from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlatformAccountCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    external_account_id: str | None = Field(default=None, max_length=120)
    company_name: str = Field(min_length=1, max_length=255)
    spoken_company_name: str | None = Field(default=None, max_length=255)
    owner_name: str | None = Field(default=None, max_length=255)
    owner_email: str | None = Field(default=None, max_length=320)


class CompanyProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(min_length=1, max_length=255)
    spoken_company_name: str | None = Field(default=None, max_length=255)
    owner_name: str | None = Field(default=None, max_length=255)
    owner_email: str | None = Field(default=None, max_length=320)


class TwilioPhoneNumberRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    phone_number: str = Field(min_length=1, max_length=20)
    friendly_name: str | None = Field(default=None, max_length=120)
    is_active: bool = True
    max_concurrent_calls: int = Field(default=1, ge=1, le=20)


class TwilioProviderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_sid: str = Field(min_length=1, max_length=64)
    auth_token: str = Field(min_length=1, max_length=255)
    webhook_base_url: str | None = Field(default=None, max_length=500)
    phone_numbers: list[TwilioPhoneNumberRequest] = Field(min_length=1)


class OpenAIProviderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: str = Field(min_length=1, max_length=255)
    realtime_model: str = Field(default="gpt-realtime-1.5", min_length=1, max_length=120)
    realtime_voice: str = Field(default="cedar", min_length=1, max_length=60)
    realtime_output_speed: float | None = Field(default=None, ge=0.25, le=1.5)
    realtime_style_instructions: str | None = None


class EmailProviderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool = True
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=255)
    smtp_use_tls: bool = True
    from_address: str | None = Field(default=None, max_length=320)
    from_name: str | None = Field(default=None, max_length=255)


class ApiTokenCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="default", min_length=1, max_length=120)
    expires_at: datetime | None = None


class TwilioPhoneNumberResponse(BaseModel):
    id: int
    phone_number: str
    friendly_name: str | None = None
    is_active: bool
    max_concurrent_calls: int


class TwilioProviderResponse(BaseModel):
    configured: bool
    account_sid_masked: str | None = None
    webhook_base_url: str | None = None
    active_phone_numbers: int = 0
    phone_numbers: list[TwilioPhoneNumberResponse] = Field(default_factory=list)


class OpenAIProviderResponse(BaseModel):
    configured: bool
    api_key_masked: str | None = None
    realtime_model: str | None = None
    realtime_voice: str | None = None
    realtime_output_speed: float | None = None
    has_style_instructions: bool = False


class EmailProviderResponse(BaseModel):
    configured: bool
    enabled: bool = False
    smtp_host: str | None = None
    from_address: str | None = None
    from_name: str | None = None


class PlatformAccountResponse(BaseModel):
    id: int
    external_account_id: str | None = None
    company_name: str
    spoken_company_name: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    status: str
    caller_company_name: str
    active_api_tokens: int
    twilio: TwilioProviderResponse
    openai: OpenAIProviderResponse
    email: EmailProviderResponse
    created_at: datetime
    updated_at: datetime


class ApiTokenCreateResponse(BaseModel):
    account_id: int
    token_id: int
    name: str
    token_prefix: str
    raw_token: str
    created_at: datetime
    expires_at: datetime | None = None
