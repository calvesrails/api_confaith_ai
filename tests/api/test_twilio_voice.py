import pytest


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
