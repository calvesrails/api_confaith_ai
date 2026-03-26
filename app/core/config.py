from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(
        default="Client Contact Validation API",
        alias="APP_NAME",
    )
    app_version: str = "0.1.0"
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_public_base_url: str | None = Field(default=None, alias="APP_PUBLIC_BASE_URL")
    platform_admin_api_key: str | None = Field(
        default=None,
        alias="PLATFORM_ADMIN_API_KEY",
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_realtime_model: str = Field(
        default="gpt-realtime-1.5",
        alias="OPENAI_REALTIME_MODEL",
    )
    openai_realtime_voice: str = Field(
        default="cedar",
        alias="OPENAI_REALTIME_VOICE",
    )
    openai_realtime_output_speed: float | None = Field(
        default=0.93,
        alias="OPENAI_REALTIME_OUTPUT_SPEED",
    )
    openai_realtime_temperature: float | None = Field(
        default=0.8,
        alias="OPENAI_REALTIME_TEMPERATURE",
    )
    openai_realtime_max_response_output_tokens: int | None = Field(
        default=220,
        alias="OPENAI_REALTIME_MAX_RESPONSE_OUTPUT_TOKENS",
    )
    openai_realtime_style_instructions: str | None = Field(
        default=(
            "Fale como uma atendente brasileira real, com voz suave, acolhedora e natural. "
            "Use pausas curtas, diccao clara, ritmo calmo de telefonia e leve sorriso na voz. "
            "Evite soar robotica, teatral ou acelerada demais."
        ),
        alias="OPENAI_REALTIME_STYLE_INSTRUCTIONS",
    )
    openai_realtime_transcription_model: str = Field(
        default="gpt-4o-transcribe",
        alias="OPENAI_REALTIME_TRANSCRIPTION_MODEL",
    )
    openai_realtime_transcription_prompt: str | None = Field(
        default=(
            "Portugues do Brasil em chamada telefonica de validacao cadastral. "
            "Priorize respostas curtas e literais, especialmente: sim, nao, e da empresa, nao e da empresa, numero errado, continua sendo."
        ),
        alias="OPENAI_REALTIME_TRANSCRIPTION_PROMPT",
    )
    openai_realtime_noise_reduction: str | None = Field(
        default="near_field",
        alias="OPENAI_REALTIME_NOISE_REDUCTION",
    )
    openai_realtime_vad_threshold: float | None = Field(
        default=None,
        alias="OPENAI_REALTIME_VAD_THRESHOLD",
    )
    openai_realtime_vad_prefix_padding_ms: int | None = Field(
        default=None,
        alias="OPENAI_REALTIME_VAD_PREFIX_PADDING_MS",
    )
    openai_realtime_vad_silence_duration_ms: int | None = Field(
        default=None,
        alias="OPENAI_REALTIME_VAD_SILENCE_DURATION_MS",
    )
    openai_realtime_vad_interrupt_response: bool = Field(
        default=False,
        alias="OPENAI_REALTIME_VAD_INTERRUPT_RESPONSE",
    )
    cnpj_base_url: str = Field(
        default="https://brasilapi.com.br/api/cnpj/v1",
        alias="CNPJ_BASE_URL",
    )
    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str | None = Field(default=None, alias="TWILIO_PHONE_NUMBER")
    twilio_webhook_base_url: str | None = Field(
        default=None,
        alias="TWILIO_WEBHOOK_BASE_URL",
    )
    database_url: str = Field(
        default="sqlite:///./contact_validation.db",
        alias="DATABASE_URL",
    )
    meta_access_token: str | None = Field(default=None, alias="META_ACCESS_TOKEN")
    meta_phone_number_id: str | None = Field(
        default=None,
        alias="META_PHONE_NUMBER_ID",
    )
    meta_verify_token: str | None = Field(default=None, alias="META_VERIFY_TOKEN")
    meta_api_version: str = Field(default="v22.0", alias="META_API_VERSION")
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from_address: str | None = Field(default=None, alias="SMTP_FROM_ADDRESS")
    smtp_from_name: str = Field(default="Central de Validacao Cadastral", alias="SMTP_FROM_NAME")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
