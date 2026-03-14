from collections.abc import AsyncIterator, Iterator
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TEST_DATABASE_PATH = Path(__file__).resolve().parent / "test_supplier_validation.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH}"

from app.db.models import ValidationBatchModel, ValidationRecordModel
from app.db.session import SessionLocal, initialize_database
from app.main import create_app

app = create_app()


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    initialize_database()
    with SessionLocal() as session:
        session.execute(delete(ValidationRecordModel))
        session.execute(delete(ValidationBatchModel))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(ValidationRecordModel))
        session.execute(delete(ValidationBatchModel))
        session.commit()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client
