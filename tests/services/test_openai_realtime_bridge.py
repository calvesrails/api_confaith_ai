import json

import pytest
from starlette.websockets import WebSocketState

from app.domain.statuses import CallResult
from app.services.openai_realtime_bridge import (
    OpenAIRealtimeBridgeService,
    RealtimeCallContext,
    _BridgeState,
)


def build_service() -> OpenAIRealtimeBridgeService:
    return OpenAIRealtimeBridgeService(
        api_key="test-key",
        model="gpt-realtime",
        voice="coral",
        transcription_model="gpt-4o-transcribe",
        transcription_prompt="Portugues do Brasil",
        noise_reduction_type="near_field",
        vad_threshold=None,
        vad_prefix_padding_ms=None,
        vad_silence_duration_ms=None,
        vad_interrupt_response=False,
    )


def test_classifies_positive_user_transcript() -> None:
    service = build_service()

    assert service._classify_transcript("Sim, continua sendo da empresa.") == CallResult.CONFIRMED


def test_classifies_negative_user_transcript() -> None:
    service = build_service()

    assert service._classify_transcript("Nao, esse numero nao pertence a empresa.") == CallResult.REJECTED


def test_classifies_positive_assistant_transcript() -> None:
    service = build_service()

    assert service._classify_assistant_transcript(
        "Certo, obrigado pela confirmacao. Validacao concluida."
    ) == CallResult.CONFIRMED


def test_normalize_text_removes_accents_and_punctuation() -> None:
    service = build_service()

    assert service._normalize_text("Nao, esse numero e da empresa!") == "nao esse numero e da empresa"


class DummyOpenAIWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send(self, data: str) -> None:
        self.messages.append(json.loads(data))


@pytest.mark.asyncio
async def test_configures_session_with_conservative_vad_settings() -> None:
    service = build_service()
    websocket = DummyOpenAIWebSocket()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Empresa Exemplo LTDA",
        cnpj="11222333000181",
        phone_dialed="+5511999999999",
    )

    await service._configure_session(websocket, context)

    assert len(websocket.messages) == 1
    session = websocket.messages[0]["session"]
    assert session["audio"]["input"]["noise_reduction"] == {"type": "near_field"}
    assert session["audio"]["input"]["turn_detection"] == {
        "type": "server_vad",
        "interrupt_response": False,
        "create_response": True,
    }


class DummyWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_requests_graceful_close_only_after_second_agent_response() -> None:
    service = build_service()
    websocket = DummyWebSocket()

    state = _BridgeState(
        classification=CallResult.CONFIRMED,
        assistant_has_responded=True,
        assistant_response_count=1,
    )

    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert websocket.closed is False

    state.assistant_response_count = 2
    state.latest_output_mark_name = "assistant-response-2-76"
    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name == "assistant-response-2-76"
    assert state.close_twilio_not_before is not None
    assert websocket.closed is False

    service._handle_twilio_mark("assistant-response-2-76", state)

    assert state.should_close_twilio is True


def test_ignores_unrelated_twilio_mark() -> None:
    service = build_service()
    state = _BridgeState(waiting_close_mark_name="assistant-response-2-76")

    service._handle_twilio_mark("assistant-response-2-77", state)

    assert state.should_close_twilio is False
