import pytest
from starlette.testclient import TestClient

from app.domain.statuses import CallResult, CallStatus
from app.main import create_app
from app.services.openai_realtime_bridge import OpenAIRealtimeBridgeService, RealtimeBridgeResult
from app.services.validation_async_service import ValidationAsyncService


pytestmark = pytest.mark.anyio


async def test_twiml_webhook_returns_stream_xml(client):
    response = await client.post(
        "/webhooks/twilio/voice/twiml"
        "?batch_id=lote_001"
        "&external_id=1"
        "&attempt_number=1"
        "&client_name=Empresa%20Exemplo%20LTDA"
        "&cnpj=11222333000181"
        "&phone_dialed=5511987654321"
    )

    assert response.status_code == 200
    assert "<Response>" in response.text
    assert "<Connect>" in response.text
    assert "<Stream" in response.text
    assert "media-stream" in response.text


async def test_twiml_webhook_returns_diagnostic_say_xml(client):
    response = await client.post(
        "/webhooks/twilio/voice/twiml"
        "?batch_id=lote_002"
        "&external_id=1"
        "&attempt_number=1"
        "&client_name=Empresa%20Exemplo%20LTDA"
        "&cnpj=11222333000181"
        "&phone_dialed=5511987654321"
        "&twiml_mode=diagnostic_say"
    )

    assert response.status_code == 200
    assert "<Response>" in response.text
    assert "<Say" in response.text
    assert "teste de diagnostico do Twilio" in response.text
    assert "<Hangup/>" in response.text
    assert "<Stream" not in response.text


def test_media_stream_route_ends_provider_call_after_final_goodbye(monkeypatch):
    ended_calls = []
    registered_events = []

    async def fake_bridge_media_stream(self, websocket):
        await websocket.accept()
        return RealtimeBridgeResult(
            batch_id="lote_media_stream",
            external_id="1",
            provider_call_id="CA_FINAL_123",
            call_status=CallStatus.ANSWERED,
            call_result=CallResult.CONFIRMED,
            transcript_summary="cliente: sim | agente: validacao concluida",
            observation="Ligacao confirmada.",
            terminate_provider_call=True,
        )

    def fake_end_provider_call_for_batch(self, batch_id: str, provider_call_id: str) -> bool:
        ended_calls.append((batch_id, provider_call_id))
        return True

    def fake_register_call_event(self, batch_id, external_id, payload):
        registered_events.append((batch_id, external_id, payload.provider_call_id, payload.call_result))

    monkeypatch.setattr(OpenAIRealtimeBridgeService, "bridge_media_stream", fake_bridge_media_stream)
    monkeypatch.setattr(ValidationAsyncService, "end_provider_call_for_batch", fake_end_provider_call_for_batch)
    monkeypatch.setattr(ValidationAsyncService, "register_call_event", fake_register_call_event)

    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/webhooks/twilio/voice/media-stream"):
            pass

    assert ended_calls == [("lote_media_stream", "CA_FINAL_123")]
    assert registered_events == [("lote_media_stream", "1", "CA_FINAL_123", CallResult.CONFIRMED)]
