import httpx
import pytest

from app.services.whatsapp_service import WhatsAppService


pytestmark = pytest.mark.anyio


def build_validation_payload(call_scenario: str = "failed") -> dict[str, str]:
    return {
        "client_name": "Empresa Exemplo LTDA",
        "cnpj": "11.222.333/0001-81",
        "phone": "11987654321",
        "call_scenario": call_scenario,
        "fallback_message": (
            "Ola, estamos validando o cadastro da empresa X. "
            "Este numero pertence a empresa? Responda SIM ou NAO."
        ),
    }


async def test_test_ui_page_is_available(client):
    response = await client.get("/test-ui")

    assert response.status_code == 200
    assert "Teste do fluxo de fallback via WhatsApp" in response.text
    assert "Simular validacao" in response.text


async def test_validate_confirmed_flow_finishes_without_whatsapp(client, monkeypatch):
    async def fail_if_called(self, phone: str, message: str):  # pragma: no cover
        raise AssertionError("WhatsApp nao deveria ser chamado para ligacao confirmada.")

    monkeypatch.setattr(WhatsAppService, "send_text_message", fail_if_called)

    response = await client.post(
        "/test/validate",
        json=build_validation_payload(call_scenario="confirmed"),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["technical_status"] == "completed"
    assert data["business_status"] == "confirmed_by_call"
    assert data["should_send_whatsapp"] is False
    assert data["whatsapp"] is None

    state_response = await client.get("/test/state")
    state = state_response.json()
    assert len(state["recent_requests"]) == 1
    assert state["recent_requests"][0]["business_status"] == "confirmed_by_call"


async def test_validate_failed_flow_sends_whatsapp_and_waits_for_reply(client, monkeypatch):
    async def fake_meta_post(self, url: str, *, headers: dict[str, str], payload: dict):
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.validation-123"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(WhatsAppService, "_post_to_meta", fake_meta_post)

    response = await client.post("/test/validate", json=build_validation_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["technical_status"] == "whatsapp_sent"
    assert data["business_status"] == "waiting_whatsapp_reply"
    assert data["flow_finished"] is False
    assert data["whatsapp"]["success"] is True
    assert data["whatsapp"]["meta_http_status"] == 200
    assert data["meta_message_id"] == "wamid.validation-123"

    state_response = await client.get("/test/state")
    state = state_response.json()
    assert state["recent_whatsapp_sends"][0]["origin"] == "test_validate"
    assert state["recent_whatsapp_sends"][0]["meta_message_id"] == "wamid.validation-123"


async def test_validate_returns_meta_error_when_send_fails(client, monkeypatch):
    async def fake_meta_post(self, url: str, *, headers: dict[str, str], payload: dict):
        return httpx.Response(
            status_code=401,
            json={"error": {"message": "Token invalido para teste."}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(WhatsAppService, "_post_to_meta", fake_meta_post)

    response = await client.post("/test/validate", json=build_validation_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["technical_status"] == "error"
    assert data["flow_finished"] is True
    assert data["whatsapp"]["success"] is False
    assert data["whatsapp"]["error_message"] == "Token invalido para teste."


async def test_manual_whatsapp_send_returns_meta_summary(client, monkeypatch):
    async def fake_meta_post(self, url: str, *, headers: dict[str, str], payload: dict):
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.manual-456"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(WhatsAppService, "_post_to_meta", fake_meta_post)

    response = await client.post(
        "/test/whatsapp/send",
        json={
            "phone": "11987654321",
            "message": "Mensagem de teste local",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "meta_http_status": 200,
        "success": True,
        "request_payload": {
            "messaging_product": "whatsapp",
            "to": "5511987654321",
            "type": "text",
            "text": {"body": "Mensagem de teste local"},
        },
        "response_payload": {"messages": [{"id": "wamid.manual-456"}]},
        "meta_message_id": "wamid.manual-456",
        "error_message": None,
    }


async def test_whatsapp_webhook_get_verifies_verify_token(client):
    response = await client.get(
        "/webhooks/whatsapp/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "local-test-verify-token",
            "hub.challenge": "abc123",
        },
    )

    assert response.status_code == 200
    assert response.text == "abc123"


async def test_whatsapp_webhook_post_updates_waiting_request_with_user_reply(
    client,
    monkeypatch,
):
    async def fake_meta_post(self, url: str, *, headers: dict[str, str], payload: dict):
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.reply-789"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(WhatsAppService, "_post_to_meta", fake_meta_post)

    create_response = await client.post("/test/validate", json=build_validation_payload())
    assert create_response.status_code == 200

    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "5511987654321",
                                    "id": "wamid.incoming-001",
                                    "text": {"body": "SIM"},
                                    "type": "text",
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }

    webhook_response = await client.post(
        "/webhooks/whatsapp/meta",
        json=webhook_payload,
    )

    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"received": True, "events_processed": 1}

    state_response = await client.get("/test/state")
    state = state_response.json()
    assert state["recent_requests"][0]["technical_status"] == "completed"
    assert state["recent_requests"][0]["business_status"] == "confirmed_by_whatsapp"
    assert state["recent_requests"][0]["last_user_reply"] == "SIM"
    assert state["last_webhook_payload"] == webhook_payload
    assert state["last_webhook_event"]["event_type"] == "message"


async def test_clear_logs_endpoint_resets_local_state(client, monkeypatch):
    async def fake_meta_post(self, url: str, *, headers: dict[str, str], payload: dict):
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.clear-111"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(WhatsAppService, "_post_to_meta", fake_meta_post)

    await client.post("/test/validate", json=build_validation_payload())
    clear_response = await client.post("/test/logs/clear", json={})

    assert clear_response.status_code == 200
    assert clear_response.json() == {
        "message": "Estado local de testes limpo com sucesso."
    }

    state_response = await client.get("/test/state")
    assert state_response.json() == {
        "recent_requests": [],
        "recent_whatsapp_sends": [],
        "logs": [],
        "last_webhook_payload": None,
        "last_webhook_event": None,
    }
