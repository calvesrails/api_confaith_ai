import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from app.domain.statuses import CallResult
from app.services.openai_realtime_bridge import (
    OpenAIRealtimeBridgeService,
    RealtimeCallContext,
    _BridgeState,
)


def build_service(*, batch_repository=None) -> OpenAIRealtimeBridgeService:
    return OpenAIRealtimeBridgeService(
        api_key="test-key",
        model="gpt-realtime",
        voice="coral",
        output_speed=0.92,
        temperature=0.8,
        max_response_output_tokens=180,
        style_instructions="Fale com calma e entonacao acolhedora.",
        transcription_model="gpt-4o-transcribe",
        transcription_prompt="Portugues do Brasil",
        noise_reduction_type="near_field",
        vad_threshold=None,
        vad_prefix_padding_ms=None,
        vad_silence_duration_ms=None,
        vad_interrupt_response=False,
        batch_repository=batch_repository,
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


def test_ignores_filler_only_transcript_for_manual_response() -> None:
    service = build_service()

    assert service._should_create_response_for_user_transcript("hum") is False
    assert service._should_create_response_for_user_transcript("aham") is False
    assert service._should_create_response_for_user_transcript("sim") is True
    assert service._should_create_response_for_user_transcript("nao pertence") is True


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
    assert session["audio"]["output"]["voice"] == "coral"
    assert session["audio"]["output"]["speed"] == 0.92
    assert session["audio"]["input"]["noise_reduction"] == {"type": "near_field"}
    assert session["audio"]["input"]["turn_detection"] == {
        "type": "server_vad",
        "interrupt_response": False,
        "create_response": False,
    }
    assert "entonacao acolhedora" in session["instructions"]


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


def test_registers_classification_to_wait_for_next_assistant_response() -> None:
    service = build_service()
    state = _BridgeState(assistant_response_count=2)

    service._register_classification(CallResult.CONFIRMED, source="user", state=state)

    assert state.classification == CallResult.CONFIRMED
    assert state.classification_source == "user"
    assert state.close_after_assistant_response_count == 3


def test_registers_user_classification_during_active_response_to_wait_for_follow_up_response() -> None:
    service = build_service()
    state = _BridgeState(assistant_response_count=0, openai_response_active=True)

    service._register_classification(CallResult.CONFIRMED, source="user", state=state)

    assert state.classification == CallResult.CONFIRMED
    assert state.close_after_assistant_response_count == 2


def test_registers_assistant_classification_to_close_after_current_active_response() -> None:
    service = build_service()
    state = _BridgeState(assistant_response_count=0, openai_response_active=True)

    service._register_classification(CallResult.CONFIRMED, source="assistant", state=state)

    assert state.classification == CallResult.CONFIRMED
    assert state.close_after_assistant_response_count == 1


@pytest.mark.asyncio
async def test_defers_response_creation_while_current_response_is_active() -> None:
    service = build_service()
    websocket = DummyOpenAIWebSocket()
    state = _BridgeState(openai_response_active=True)

    created = await service._request_openai_response(
        websocket,
        state,
        allow_defer=True,
    )

    assert created is False
    assert state.pending_response_create is True
    assert websocket.messages == []

    created = await service._request_openai_response(
        websocket,
        state,
        allow_defer=False,
    )

    assert created is True
    assert state.pending_response_create is False
    assert state.openai_response_active is True
    assert websocket.messages == [{"type": "response.create"}]


@pytest.mark.asyncio
async def test_waits_for_response_after_late_classification_before_closing() -> None:
    service = build_service()
    websocket = DummyWebSocket()
    state = _BridgeState(
        classification=CallResult.REJECTED,
        classification_source="user",
        close_after_assistant_response_count=3,
        assistant_has_responded=True,
        assistant_response_count=2,
    )

    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name is None

    state.assistant_response_count = 3
    state.latest_output_mark_name = "assistant-response-3-81"
    state.last_assistant_response_classification = CallResult.REJECTED
    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name == "assistant-response-3-81"


@pytest.mark.asyncio
async def test_configures_session_with_context_voice_overrides() -> None:
    service = build_service()
    websocket = DummyOpenAIWebSocket()
    context = RealtimeCallContext(
        batch_id="batch-override",
        external_id="2",
        attempt_number=1,
        client_name="Empresa Teste SA",
        cnpj="11222333000181",
        phone_dialed="+5511999999999",
        realtime_model_override="gpt-realtime-1.5",
        realtime_voice_override="cedar",
        realtime_output_speed_override=0.93,
        realtime_style_profile="calm_slow",
    )

    await service._configure_session(websocket, context)

    session = websocket.messages[0]["session"]
    assert session["audio"]["output"]["voice"] == "cedar"
    assert session["audio"]["output"]["speed"] == 0.93
    assert "Fale um pouco mais devagar" in session["instructions"]


def test_build_context_parses_realtime_overrides() -> None:
    service = build_service()

    context = service._build_context(
        {
            "batch_id": "batch-ctx",
            "external_id": "7",
            "attempt_number": "2",
            "client_name": "Empresa Contexto",
            "cnpj": "11222333000181",
            "phone_dialed": "+5511999999999",
            "realtime_model": "gpt-realtime-1.5",
            "realtime_voice": "cedar",
            "realtime_output_speed": "0.93",
            "realtime_style_profile": "bright_friendly",
        }
    )

    assert context.realtime_model_override == "gpt-realtime-1.5"
    assert context.realtime_voice_override == "cedar"
    assert context.realtime_output_speed_override == 0.93
    assert context.realtime_style_profile == "bright_friendly"


@pytest.mark.asyncio
async def test_does_not_close_when_follow_up_assistant_response_is_only_a_reprompt() -> None:
    service = build_service()
    websocket = DummyWebSocket()
    state = _BridgeState(
        classification=CallResult.REJECTED,
        classification_source="user",
        close_after_assistant_response_count=2,
        assistant_has_responded=True,
        assistant_response_count=2,
        latest_output_mark_name="assistant-response-2-65",
        last_assistant_response_classification=None,
    )

    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name is None
    assert state.close_after_assistant_response_count == 3


@pytest.mark.asyncio
async def test_closes_after_follow_up_assistant_response_when_it_is_conclusive() -> None:
    service = build_service()
    websocket = DummyWebSocket()
    state = _BridgeState(
        classification=CallResult.REJECTED,
        classification_source="user",
        close_after_assistant_response_count=2,
        assistant_has_responded=True,
        assistant_response_count=2,
        latest_output_mark_name="assistant-response-2-65",
        last_assistant_response_classification=CallResult.REJECTED,
    )

    await service._maybe_close_twilio_stream(websocket, state)

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name == "assistant-response-2-65"


def test_hydrate_context_from_batch_loads_account_specific_runtime_config() -> None:
    batch_repository = SimpleNamespace(
        get_batch_model=lambda batch_id: SimpleNamespace(
            batch_id=batch_id,
            caller_company_name=None,
            platform_account=SimpleNamespace(
                company_name="XPTO Assessoria",
                spoken_company_name="XPTO Validacao",
                openai_credential=SimpleNamespace(
                    api_key="sk-account-key",
                    realtime_model="gpt-realtime-1.5",
                    realtime_voice="cedar",
                    realtime_output_speed=0.93,
                    realtime_style_instructions="Fale com mais proximidade e naturalidade.",
                ),
            ),
        )
    )
    service = build_service(batch_repository=batch_repository)
    context = RealtimeCallContext(
        batch_id="batch-account",
        external_id="1",
        attempt_number=1,
        client_name="Fornecedor Exemplo LTDA",
        cnpj="11222333000181",
        phone_dialed="+5511999999999",
    )

    service._hydrate_context_from_batch(context)

    assert context.caller_company_name == "XPTO Validacao"
    assert context.resolved_api_key == "sk-account-key"
    assert context.resolved_model == "gpt-realtime-1.5"
    assert context.resolved_voice == "cedar"
    assert context.resolved_output_speed == 0.93
    assert "XPTO Validacao" in service._build_instructions(context)
