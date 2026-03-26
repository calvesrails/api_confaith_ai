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
    assert service._classify_transcript("Certeza.") == CallResult.CONFIRMED




def test_classifies_contextual_affirmative_for_cadastral_confirmation() -> None:
    service = build_service()
    state = _BridgeState()

    service._capture_cadastral_question_state(
        "Esse contato pertence a empresa?",
        state,
    )

    assert service._classify_transcript(
        "Perfeitissimo.",
        state=state,
    ) == CallResult.CONFIRMED


def test_does_not_classify_contextual_affirmative_without_pending_question() -> None:
    service = build_service()

    assert service._classify_transcript("Perfeitissimo.") is None

def test_classifies_negative_user_transcript() -> None:
    service = build_service()

    assert service._classify_transcript("Nao, esse numero nao pertence a empresa.") == CallResult.REJECTED


def test_does_not_classify_customer_question_as_confirmation() -> None:
    service = build_service()

    assert service._classify_transcript("Quem esta falando? Por que voces querem confirmar esse numero?") is None


def test_does_not_classify_social_reply_as_confirmation() -> None:
    service = build_service()

    assert service._classify_transcript("Estou bem, e voce?") is None


def test_classifies_confirmation_even_when_followed_by_question() -> None:
    service = build_service()

    assert service._classify_transcript("Sim, continua sendo da empresa, mas de onde voces sao?") == CallResult.CONFIRMED


def test_classifies_positive_assistant_transcript() -> None:
    service = build_service()

    assert service._classify_assistant_transcript(
        "Certo, obrigado pela confirmacao. Validacao concluida."
    ) == CallResult.CONFIRMED


def test_runtime_ignores_assistant_only_confirmation_in_cadastral_flow() -> None:
    service = build_service()
    state = _BridgeState(
        context=RealtimeCallContext(
            batch_id="batch-1",
            external_id="1",
            attempt_number=1,
            client_name="Empresa Exemplo LTDA",
            cnpj="11222333000181",
            phone_dialed="+5511999999999",
            workflow_kind="cadastral_validation",
        )
    )

    assert service._should_accept_assistant_classification(
        CallResult.CONFIRMED,
        state=state,
    ) is False

    state.classification = CallResult.CONFIRMED
    state.classification_source = "user"

    assert service._should_accept_assistant_classification(
        CallResult.CONFIRMED,
        state=state,
    ) is True


def test_normalize_text_removes_accents_and_punctuation() -> None:
    service = build_service()

    assert service._normalize_text("Nao, esse numero e da empresa!") == "nao esse numero e da empresa"


def test_supplier_flow_confirms_split_answers_across_multiple_turns() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(context=context)

    service._capture_supplier_question_state("Esse numero pertence a empresa Terra Vegetal e Adubo?", state)
    assert service._classify_transcript("Sim", context, state=state) is None
    assert state.supplier_phone_belongs_confirmed is True

    service._capture_supplier_question_state("Perfeito. Voces fornecem adubo?", state)
    assert service._classify_transcript("Sim", context, state=state) is None
    assert state.supplier_supplies_segment_confirmed is True

    service._capture_supplier_question_state("Posso registrar esse telefone para retorno do comercial?", state)
    assert service._classify_transcript("Pode sim", context, state=state) == CallResult.CONFIRMED
    assert state.supplier_callback_accept_confirmed is True


def test_supplier_flow_rejects_simple_negative_answer_for_active_question() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(context=context)

    service._capture_supplier_question_state("Voces fornecem adubo?", state)
    assert service._classify_transcript("Nao", context, state=state) == CallResult.REJECTED


def test_supplier_flow_accepts_social_phrase_with_business_signal() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(context=context)

    service._capture_supplier_question_state("Voces podem receber retorno comercial?", state)
    assert service._classify_transcript("Bom dia, pode falar com o comercial sim.", context, state=state) is None
    assert state.supplier_callback_accept_confirmed is True


def test_supplier_flow_combined_contact_and_segment_answer_marks_both_points() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(context=context)

    service._capture_supplier_question_state("Esse contato aqui pertence a empresa Terra Vegetal e Adubo e voces realmente fornecem adubo?", state)

    assert state.pending_supplier_question == "phone_belongs"
    assert service._classify_transcript("Sim, pertencem, fornecemos.", context, state=state) is None
    assert state.supplier_phone_belongs_confirmed is True
    assert state.supplier_supplies_segment_confirmed is True


def test_supplier_goodbye_after_complete_state_is_treated_as_confirmed() -> None:
    service = build_service()
    state = _BridgeState(
        supplier_phone_belongs_confirmed=True,
        supplier_supplies_segment_confirmed=True,
        supplier_callback_accept_confirmed=True,
    )

    assert service._classify_assistant_transcript(
        "Imagina, eu que agradeco a atencao. Qualquer coisa estamos por aqui. Um abraco e um otimo dia pra voce.",
        state=state,
    ) == CallResult.CONFIRMED


def test_supplier_assistant_acknowledges_confirmation_as_positive_signal() -> None:
    service = build_service()
    state = _BridgeState()

    assert service._classify_assistant_transcript(
        "Maravilha, agradeco pela confirmacao. Qualquer duvida, estamos a disposicao. Tenha um otimo dia!",
        state=state,
    ) == CallResult.CONFIRMED
    assert service._classify_assistant_transcript(
        "Otimo, agradeco a confirmacao. Obrigada e um bom dia para voce!",
        state=state,
    ) == CallResult.CONFIRMED


def test_supplier_runtime_does_not_confirm_mid_question_after_partial_confirmation() -> None:
    service = build_service()
    state = _BridgeState(
        context=RealtimeCallContext(
            batch_id="batch-1",
            external_id="1",
            attempt_number=1,
            client_name="Terra Vegetal e Adubo",
            cnpj="",
            phone_dialed="+5511999999999",
            workflow_kind="supplier_validation",
            segment_name="Adubo",
        ),
        supplier_phone_belongs_confirmed=True,
    )

    assert service._classify_assistant_transcript(
        "Perfeito, obrigada pela confirmacao. E a empresa de voces realmente fornece adubo?",
        state=state,
    ) is None








def test_supplier_negative_answer_sets_reason_from_pending_question() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(context=context, pending_supplier_question="supplies_segment")

    assert service._classify_transcript("Nao fornecemos.", context, state=state) == CallResult.REJECTED
    assert state.supplier_rejection_reason == "supplies_segment"


@pytest.mark.asyncio
async def test_request_openai_response_injects_supplier_rejection_close_prompt() -> None:
    service = build_service()
    websocket = DummyOpenAIWebSocket()
    state = _BridgeState(
        context=RealtimeCallContext(
            batch_id="batch-1",
            external_id="1",
            attempt_number=1,
            client_name="Terra Vegetal e Adubo",
            cnpj="",
            phone_dialed="+5511999999999",
            workflow_kind="supplier_validation",
            segment_name="Adubo",
        ),
        supplier_rejection_reason="supplies_segment",
        pending_response_instruction="Agora responda apenas com um agradecimento curto e uma despedida final.",
    )

    await service._request_openai_response(websocket, state, allow_defer=False)

    assert websocket.messages[0]["type"] == "conversation.item.create"
    assert websocket.messages[1]["type"] == "response.create"
    assert state.pending_response_instruction is None


@pytest.mark.asyncio
async def test_supplier_user_rejection_goodbye_can_close_without_matching_assistant_classification() -> None:
    service = build_service()
    websocket = DummyWebSocket()
    state = _BridgeState(
        context=RealtimeCallContext(
            batch_id="batch-1",
            external_id="1",
            attempt_number=1,
            client_name="Terra Vegetal e Adubo",
            cnpj="",
            phone_dialed="+5511999999999",
            workflow_kind="supplier_validation",
            segment_name="Adubo",
        ),
        classification=CallResult.REJECTED,
        classification_source="user",
        assistant_signaled_goodbye=True,
        assistant_response_count=4,
        close_after_assistant_response_count=4,
        latest_output_mark_name="assistant-response-4-60",
        last_assistant_response_classification=None,
    )

    await service._maybe_close_twilio_stream(websocket, state)

    assert state.waiting_close_mark_name == "assistant-response-4-60"

def test_supplier_flow_does_not_count_phone_answer_as_segment_confirmation() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Terra Vegetal e Adubo",
        cnpj="",
        phone_dialed="+5511999999999",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511999999999",
    )
    state = _BridgeState(
        context=context,
        supplier_phone_belongs_confirmed=True,
        pending_supplier_question="supplies_segment",
    )

    assert service._classify_transcript(
        "Sim, e da empresa.", context, state=state
    ) is None
    assert state.supplier_phone_belongs_confirmed is True
    assert state.supplier_supplies_segment_confirmed is False
    assert state.pending_supplier_question == "supplies_segment"


def test_supplier_initial_prompt_stops_after_negative_answer() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Empresa Exemplo LTDA",
        cnpj="",
        phone_dialed="+5511999999999",
        caller_company_name="XPTO Validacao",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
    )

    prompt = service._build_initial_turn_prompt(context)

    assert "Se a resposta for negativa, agradeca e encerre" in prompt

def test_supplier_initial_prompt_asks_one_question_at_a_time() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Empresa Exemplo LTDA",
        cnpj="",
        phone_dialed="+5511999999999",
        caller_company_name="XPTO Validacao",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
    )

    prompt = service._build_initial_turn_prompt(context)

    assert "Faca somente a primeira pergunta" in prompt
    assert "Aguarde a resposta." in prompt
    assert "Faca somente a segunda pergunta" in prompt
    assert "Faca somente a terceira pergunta" in prompt


def test_matching_twilio_mark_releases_input_capture_guard() -> None:
    service = build_service()
    state = _BridgeState(ignore_twilio_audio_until_mark_name="assistant-response-3-58")

    service._handle_twilio_mark("assistant-response-3-58", state)

    assert state.ignore_twilio_audio_until_mark_name is None
    assert state.ignore_twilio_audio_until is not None


def test_matching_twilio_mark_for_graceful_close_does_not_reopen_user_capture() -> None:
    service = build_service()
    state = _BridgeState(
        ignore_twilio_audio_until_mark_name="assistant-response-3-58",
        waiting_close_mark_name="assistant-response-3-58",
    )

    service._handle_twilio_mark("assistant-response-3-58", state)

    assert state.should_close_twilio is True
    assert state.waiting_close_mark_name is None
    assert state.ignore_twilio_audio_until_mark_name == "assistant-response-3-58"
    assert state.ignore_twilio_audio_until is None


def test_cadastral_accepts_assistant_confirmation_after_substantive_customer_reply() -> None:
    service = build_service()
    state = _BridgeState()

    service._capture_cadastral_question_state(
        "Esse contato pertence a empresa?",
        state,
    )

    assert state.pending_cadastral_confirmation_question is True

    assert service._is_substantive_cadastral_confirmation_reply("Verdense?") is True

    state.cadastral_confirmation_response_received = True

    assert (
        service._should_accept_assistant_classification(
            CallResult.CONFIRMED,
            state=state,
        )
        is True
    )


def test_supplier_goodbye_statement_does_not_reopen_callback_question() -> None:
    service = build_service()
    state = _BridgeState()

    service._capture_supplier_question_state(
        "Otimo, agradeco a confirmacao. Se precisar, nosso interesse e apenas para contato comercial mesmo. Obrigada e um bom dia para voce!",
        state,
    )

    assert state.pending_supplier_question is None

def test_detects_final_goodbye_from_assistant_transcript() -> None:
    service = build_service()

    assert service._assistant_transcript_signals_final_goodbye(
        "Imagina, eu que agradeco a atencao. Qualquer coisa estamos por aqui. Um abraco e um otimo dia pra voce."
    ) is True
    assert service._assistant_transcript_signals_final_goodbye(
        "Otimo, agradeco a confirmacao. Obrigada e um bom dia para voce!"
    ) is True
    assert service._assistant_transcript_signals_final_goodbye("Boa tarde, tudo bem com voce?") is False


def test_ignores_filler_only_transcript_for_manual_response() -> None:
    service = build_service()

    assert service._should_create_response_for_user_transcript("hum") is False
    assert service._should_create_response_for_user_transcript("aham") is False
    assert service._should_create_response_for_user_transcript("tudo bem") is False
    assert service._should_create_response_for_user_transcript("oi tudo bem") is False
    assert service._should_create_response_for_user_transcript("Estou bem, e voce?") is True
    assert service._should_create_response_for_user_transcript("sim") is True
    assert service._should_create_response_for_user_transcript("nao pertence") is True


def test_allows_short_greeting_reply_only_after_first_assistant_opening() -> None:
    service = build_service()
    state = _BridgeState(assistant_response_count=1)

    assert service._should_create_response_for_user_transcript(
        "Tudo bem",
        state=state,
    ) is True

    state.assistant_response_count = 2

    assert service._should_create_response_for_user_transcript(
        "Tudo bem",
        state=state,
    ) is False


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
async def test_start_agent_turn_uses_conversational_opening_without_cnpj() -> None:
    service = build_service()
    websocket = DummyOpenAIWebSocket()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Empresa Exemplo LTDA",
        cnpj="11222333000181",
        phone_dialed="+5511999999999",
        caller_company_name="XPTO Validacao",
    )
    state = _BridgeState()

    await service._start_agent_turn(websocket, context, state)

    assert websocket.messages[0]["type"] == "conversation.item.create"
    prompt_text = websocket.messages[0]["item"]["content"][0]["text"]
    assert "Primeiro cumprimente de forma natural" in prompt_text
    assert "XPTO Validacao" in prompt_text
    assert context.client_name in prompt_text
    assert "sem dizer nome proprio" in prompt_text
    assert context.cnpj not in prompt_text
    assert context.phone_dialed not in prompt_text
    assert websocket.messages[1]["type"] == "response.create"


def test_supplier_instructions_identify_only_company_without_spoken_phone_number() -> None:
    service = build_service()
    context = RealtimeCallContext(
        batch_id="batch-1",
        external_id="1",
        attempt_number=1,
        client_name="Empresa Exemplo LTDA",
        cnpj="",
        phone_dialed="+5511999999999",
        caller_company_name="XPTO Validacao",
        workflow_kind="supplier_validation",
        segment_name="Adubo",
        callback_phone="+5511888888888",
        callback_contact_name="Marina",
    )

    instructions = service._build_instructions(context)

    assert "XPTO Validacao" in instructions
    assert "sem dizer nome proprio" in instructions
    assert "Nao diga nome proprio" in instructions
    assert "encerre a chamada sem aguardar nova resposta do cliente" in instructions
    assert "Faca exatamente uma pergunta de negocio por vez" in instructions
    assert "Nunca junte confirmacao de numero, segmento e retorno comercial na mesma pergunta" in instructions
    assert context.phone_dialed not in instructions
    assert context.callback_phone not in instructions
    assert "esse numero" in instructions
    assert "retorno comercial por esse contato" in instructions


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
    assert state.waiting_close_mark_name is None


def test_ignores_unrelated_twilio_mark() -> None:
    service = build_service()
    state = _BridgeState(waiting_close_mark_name="assistant-response-2-76")

    service._handle_twilio_mark("assistant-response-2-77", state)

    assert state.should_close_twilio is False


def test_requests_graceful_close_after_assistant_goodbye_even_without_classification() -> None:
    service = build_service()
    state = _BridgeState(
        assistant_has_responded=True,
        assistant_response_count=1,
        latest_output_mark_name="assistant-response-1-34",
    )

    service._request_graceful_close_after_current_audio(
        state,
        reason="despedida final da assistente",
    )

    assert state.should_close_twilio is False
    assert state.waiting_close_mark_name == "assistant-response-1-34"
    assert state.close_twilio_not_before is not None


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
    instructions = service._build_instructions(context)
    assert "XPTO Validacao" in instructions
    assert "espere a pessoa responder antes de explicar o motivo da ligacao" in instructions
    assert "estou bem e voce" in instructions
    assert "por que precisa confirmar o numero" in instructions
    assert "perguntas laterais nao contam como confirmacao" in instructions
    assert context.cnpj not in instructions
