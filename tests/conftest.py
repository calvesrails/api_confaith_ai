from collections.abc import AsyncIterator, Iterator
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

TEST_DATABASE_PATH = Path("/tmp") / "api_confaith_ai_test_contact_validation.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH}"
os.environ["META_ACCESS_TOKEN"] = "test-meta-token"
os.environ["META_PHONE_NUMBER_ID"] = "123456789"
os.environ["META_VERIFY_TOKEN"] = "local-test-verify-token"
os.environ["APP_NAME"] = "Client Contact Validation API"
os.environ["APP_ENV"] = "test"
os.environ["APP_DEBUG"] = "true"
os.environ["CNPJ_BASE_URL"] = "https://brasilapi.com.br/api/cnpj/v1"
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["TWILIO_PHONE_NUMBER"] = ""
os.environ["TWILIO_WEBHOOK_BASE_URL"] = "https://example.ngrok-free.app"
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_REALTIME_VOICE"] = "marin"
os.environ["OPENAI_REALTIME_TRANSCRIPTION_MODEL"] = "gpt-4o-transcribe"
os.environ["OPENAI_REALTIME_TRANSCRIPTION_PROMPT"] = "Portugues do Brasil em chamada telefonica de validacao cadastral. Priorize respostas curtas e literais, especialmente: sim, nao, e da empresa, nao e da empresa, numero errado, continua sendo."

from app.core.memory_store import get_memory_store
from app.db.base import Base
from app.db.session import engine, initialize_database
from app.main import create_app
from app.services.official_company_registry_service import OfficialCompanyRegistryService

app = create_app()


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    Base.metadata.drop_all(bind=engine)
    initialize_database()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_memory_store() -> Iterator[None]:
    memory_store = get_memory_store()
    memory_store.reset()
    yield
    memory_store.reset()


@pytest.fixture(autouse=True)
def mock_official_company_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def fake_fetch_company_data(
        self: OfficialCompanyRegistryService,
        cnpj: str | None,
    ) -> dict[str, str] | None:
        normalized_cnpj = "".join(char for char in str(cnpj or "") if char.isdigit())
        if normalized_cnpj != "11222333000181":
            return None

        return {
            "cnpj": normalized_cnpj,
            "razao_social": "EMPRESA EXEMPLO LTDA",
            "nome_fantasia": "EMPRESA EXEMPLO",
            "ddd_telefone_1": "11987654321",
            "ddd_telefone_2": "",
        }

    monkeypatch.setattr(
        OfficialCompanyRegistryService,
        "fetch_company_data",
        fake_fetch_company_data,
    )
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client
