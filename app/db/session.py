from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from .base import Base
from .models import (
    ApiTokenModel,
    CallAttemptModel,
    EmailMessageModel,
    EmailSenderProfileModel,
    OpenAICredentialModel,
    PlatformAccountModel,
    TwilioCredentialModel,
    TwilioPhoneNumberModel,
    ValidationBatchModel,
    ValidationRecordModel,
    WhatsAppMessageModel,
)

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith(
    "sqlite"
) else {}

engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


_VALIDATION_RECORD_COLUMN_MIGRATIONS = {
    "email_original": "VARCHAR(320)",
    "email_normalized": "VARCHAR(320)",
    "official_registry_email": "VARCHAR(320)",
    "email_status": "VARCHAR(40) DEFAULT 'not_required'",
}

_VALIDATION_BATCH_COLUMN_MIGRATIONS = {
    "platform_account_id": "INTEGER",
    "api_token_id": "INTEGER",
    "caller_company_name": "VARCHAR(255)",
    "public_batch_id": "VARCHAR(120)",
}

_CALL_ATTEMPT_COLUMN_MIGRATIONS = {
    "from_phone_number_used": "VARCHAR(20)",
}


def _apply_sqlite_table_migrations(
    table_name: str,
    migrations: dict[str, str],
) -> None:
    if not _settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        try:
            result = connection.exec_driver_sql(f"PRAGMA table_info({table_name})")
        except Exception:
            return

        existing_columns = {row[1] for row in result.fetchall()}
        for column_name, column_sql in migrations.items():
            if column_name in existing_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
            )


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_table_migrations(
        "validation_records",
        _VALIDATION_RECORD_COLUMN_MIGRATIONS,
    )
    _apply_sqlite_table_migrations(
        "validation_batches",
        _VALIDATION_BATCH_COLUMN_MIGRATIONS,
    )
    _apply_sqlite_table_migrations(
        "call_attempts",
        _CALL_ATTEMPT_COLUMN_MIGRATIONS,
    )


async def get_db_session() -> AsyncIterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
