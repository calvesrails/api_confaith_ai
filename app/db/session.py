from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from .base import Base
from .models import (
    CallAttemptModel,
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


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)


async def get_db_session() -> AsyncIterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
