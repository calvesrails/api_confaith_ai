from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Supplier Validation API"
    app_version: str = "0.1.0"
    database_url: str = Field(
        default="sqlite:///./supplier_validation.db",
        alias="DATABASE_URL",
    )
    known_cnpjs: list[str] = Field(default_factory=list, alias="KNOWN_CNPJS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("known_cnpjs", mode="before")
    @classmethod
    def split_known_cnpjs(cls, value: object) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise TypeError("KNOWN_CNPJS must be a comma-separated string or a list")


@lru_cache
def get_settings() -> Settings:
    return Settings()
