import pytest


pytestmark = pytest.mark.anyio


async def test_health_check_returns_service_metadata(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Client Contact Validation API",
        "version": "0.1.0",
    }
