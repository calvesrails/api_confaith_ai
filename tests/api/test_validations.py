import pytest

from app.services.official_company_registry_service import OfficialCompanyRegistryService
from app.services.twilio_voice_service import TwilioCallDispatchResult, TwilioVoiceService


pytestmark = pytest.mark.anyio


def build_valid_record(external_id: str = "1") -> dict:
    return {
        "external_id": external_id,
        "client_name": "Empresa Exemplo LTDA",
        "cnpj": "11.222.333/0001-81",
        "phone": "11987654321",
    }


async def test_create_validation_batch_returns_received_snapshot_for_rails_polling(client):
    payload = {
        "id_lote": "lote_001",
        "origem": "web",
        "records": [
            {
                "id_registro": "1",
                "nome_cliente": "Empresa Exemplo LTDA",
                "cnpj": "11.222.333/0001-81",
                "telefone": "(11) 98765-4321",
            },
            {
                "external_id": "2",
                "client_name": "Cliente Telefone Invalido",
                "cnpj": "11.222.333/0001-81",
                "phone": "1234",
            },
        ],
    }

    response = await client.post("/validations", json=payload)

    assert response.status_code == 202

    data = response.json()
    assert data["batch_id"] == "lote_001"
    assert data["source"] == "web"
    assert data["batch_status"] == "received"
    assert data["result_ready"] is False
    assert data["technical_status"] == "received"
    assert data["finished_at"] is None
    assert data["total_records"] == 2
    assert data["summary"] == {
        "ready_for_call": 1,
        "ready_for_retry_call": 0,
        "validation_failed": 1,
        "invalid_phone": 1,
        "cnpj_not_found": 0,
        "processing": 1,
        "pending_records": 1,
        "validated_records": 0,
        "failed_records": 1,
        "confirmed_by_call": 0,
        "confirmed_by_whatsapp": 0,
        "waiting_whatsapp_reply": 0,
    }

    first_record = data["records"][0]
    assert first_record["external_id"] == "1"
    assert first_record["cnpj_normalized"] == "11222333000181"
    assert first_record["phone_normalized"] == "5511987654321"
    assert first_record["call_status"] == "not_started"
    assert first_record["call_result"] == "not_started"
    assert first_record["final_status"] == "processing"
    assert first_record["call_attempts"] == []
    assert first_record["whatsapp_history"] == []

    second_record = data["records"][1]
    assert second_record["phone_valid"] is False
    assert second_record["business_status"] == "invalid_phone"
    assert second_record["final_status"] == "validation_failed"


async def test_dispatch_moves_batch_to_processing_and_creates_initial_call_attempt(client):
    payload = {
        "batch_id": "lote_dispatch",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)

    dispatch_response = await client.post("/validations/lote_dispatch/dispatch")

    assert dispatch_response.status_code == 200
    data = dispatch_response.json()
    assert data["batch_status"] == "processing"
    assert data["result_ready"] is False
    assert data["summary"]["pending_records"] == 1
    assert data["records"][0]["call_status"] == "queued"
    assert data["records"][0]["call_result"] == "pending_dispatch"
    assert len(data["records"][0]["call_attempts"]) == 1
    assert data["records"][0]["call_attempts"][0]["status"] == "queued"
    assert data["records"][0]["call_attempts"][0]["phone_source"] == "payload_phone"


async def test_dispatch_uses_twilio_when_provider_is_configured(client, monkeypatch):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: True)

    def fake_create_outbound_call(
        self,
        *,
        batch_id: str,
        external_id: str,
        attempt_number: int,
        client_name: str,
        cnpj: str,
        phone_to_dial: str,
        twiml_mode: str = "media_stream",
    ) -> TwilioCallDispatchResult:
        assert batch_id == "lote_twilio"
        assert external_id == "1"
        assert attempt_number == 1
        assert client_name == "Empresa Exemplo LTDA"
        assert cnpj == "11222333000181"
        assert phone_to_dial == "5511987654321"
        assert twiml_mode == "media_stream"
        return TwilioCallDispatchResult(
            provider_call_id="CA1234567890",
            provider_status="queued",
            raw_payload={"sid": "CA1234567890", "status": "queued"},
        )

    monkeypatch.setattr(TwilioVoiceService, "create_outbound_call", fake_create_outbound_call)

    payload = {
        "batch_id": "lote_twilio",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    dispatch_response = await client.post("/validations/lote_twilio/dispatch")

    assert dispatch_response.status_code == 200
    data = dispatch_response.json()
    assert data["records"][0]["call_attempts"][0]["provider_call_id"] == "CA1234567890"
    assert "Twilio Voice" not in data["records"][0]["observation"]


async def test_rejected_call_queues_retry_on_alternative_phone_found_in_registry(
    client,
    monkeypatch,
):
    def fake_fetch_company_data(self, cnpj: str | None):
        assert cnpj == "11222333000181"
        return {
            "cnpj": "11222333000181",
            "razao_social": "EMPRESA EXEMPLO LTDA",
            "ddd_telefone_1": "11999990000",
            "ddd_telefone_2": "",
        }

    monkeypatch.setattr(
        OfficialCompanyRegistryService,
        "fetch_company_data",
        fake_fetch_company_data,
    )

    payload = {
        "batch_id": "lote_retry_phone",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    await client.post("/validations/lote_retry_phone/dispatch")
    batch_response = await client.get("/validations/lote_retry_phone")
    provider_call_id = batch_response.json()["records"][0]["call_attempts"][0]["provider_call_id"]

    response = await client.post(
        "/validations/lote_retry_phone/records/1/call-events",
        json={
            "provider_call_id": provider_call_id,
            "call_status": "answered",
            "call_result": "rejected",
            "transcript_summary": "Contato informou que o numero nao pertence a empresa.",
            "sentiment": "neutral",
            "duration_seconds": 35,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["business_status"] == "ready_for_retry_call"
    assert data["call_status"] == "queued"
    assert data["call_result"] == "pending_dispatch"
    assert data["final_status"] == "processing"
    assert data["whatsapp_status"] == "not_required"
    assert len(data["call_attempts"]) == 2
    assert data["call_attempts"][1]["phone_dialed"] == "5511999990000"
    assert data["call_attempts"][1]["phone_source"] == "official_company_registry"

    batch_result = await client.get("/validations/lote_retry_phone")
    batch_data = batch_result.json()
    assert batch_data["batch_status"] == "processing"
    assert batch_data["summary"]["ready_for_retry_call"] == 1
    assert batch_data["summary"]["waiting_whatsapp_reply"] == 0


async def test_twilio_completed_after_answer_keeps_record_processing_until_media_stream_result(
    client,
):
    payload = {
        "batch_id": "lote_completed_after_answer",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    await client.post("/validations/lote_completed_after_answer/dispatch")
    batch_response = await client.get("/validations/lote_completed_after_answer")
    provider_call_id = batch_response.json()["records"][0]["call_attempts"][0]["provider_call_id"]

    answered_response = await client.post(
        "/webhooks/twilio/voice/status?batch_id=lote_completed_after_answer&external_id=1&attempt_number=1",
        data={
            "CallSid": provider_call_id,
            "CallStatus": "in-progress",
            "CallDuration": "12",
        },
    )

    assert answered_response.status_code == 200

    completed_response = await client.post(
        "/webhooks/twilio/voice/status?batch_id=lote_completed_after_answer&external_id=1&attempt_number=1",
        data={
            "CallSid": provider_call_id,
            "CallStatus": "completed",
            "CallDuration": "24",
        },
    )

    assert completed_response.status_code == 200

    intermediate_batch_response = await client.get("/validations/lote_completed_after_answer")
    data = intermediate_batch_response.json()
    assert data["batch_status"] == "processing"
    assert data["result_ready"] is False
    assert data["summary"]["pending_records"] == 1
    assert data["records"][0]["final_status"] == "processing"
    assert data["records"][0]["call_status"] == "answered"
    assert data["records"][0]["business_status"] == "call_answered"

    final_response = await client.post(
        "/validations/lote_completed_after_answer/records/1/call-events",
        json={
            "provider_call_id": provider_call_id,
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "cliente: sim continua sendo da empresa | agente: obrigada validacao concluida com sucesso",
            "duration_seconds": 24,
            "observation": "Numero confirmado por ligacao conversacional.",
        },
    )

    assert final_response.status_code == 200
    final_data = final_response.json()
    assert final_data["final_status"] == "validated"
    assert final_data["business_status"] == "confirmed_by_call"
    assert final_data["phone_confirmed"] is True


async def test_twilio_completed_without_media_stream_finalizes_batch_with_inconclusive_error(
    client,
):
    payload = {
        "batch_id": "lote_completed_without_media",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    await client.post("/validations/lote_completed_without_media/dispatch")
    batch_response = await client.get("/validations/lote_completed_without_media")
    provider_call_id = batch_response.json()["records"][0]["call_attempts"][0]["provider_call_id"]

    response = await client.post(
        "/webhooks/twilio/voice/status?batch_id=lote_completed_without_media&external_id=1&attempt_number=1",
        data={
            "CallSid": provider_call_id,
            "CallStatus": "completed",
            "CallDuration": "24",
        },
    )

    assert response.status_code == 200

    final_batch_response = await client.get("/validations/lote_completed_without_media")
    data = final_batch_response.json()
    assert data["batch_status"] == "completed"
    assert data["result_ready"] is True
    assert data["summary"]["pending_records"] == 0
    assert data["summary"]["failed_records"] == 1
    assert data["records"][0]["final_status"] == "validation_failed"
    assert data["records"][0]["business_status"] == "inconclusive_call"
    assert data["records"][0]["call_result"] == "inconclusive"


async def test_batch_is_completed_immediately_when_all_records_fail_initial_validation(client):
    payload = {
        "batch_id": "lote_invalidos",
        "source": "web",
        "records": [
            {
                "external_id": "1",
                "client_name": "Cliente Invalido",
                "cnpj": "123",
                "phone": "999",
            }
        ],
    }

    response = await client.post("/validations", json=payload)

    assert response.status_code == 202
    data = response.json()
    assert data["batch_status"] == "completed"
    assert data["result_ready"] is True
    assert data["finished_at"] is not None
    assert data["summary"]["pending_records"] == 0
    assert data["summary"]["failed_records"] == 1
    assert data["records"][0]["final_status"] == "validation_failed"


async def test_create_validation_batch_returns_payload_error_for_invalid_body(client):
    payload = {"batch_id": "lote_002", "source": "web", "records": []}

    response = await client.post("/validations", json=payload)

    assert response.status_code == 422

    data = response.json()
    assert data["message"] == "Payload inválido."
    assert data["technical_status"] == "payload_invalid"
    assert data["errors"]


async def test_create_validation_batch_rejects_duplicate_batch_id(client):
    payload = {
        "batch_id": "lote_duplicado",
        "source": "web",
        "records": [build_valid_record()],
    }

    first_response = await client.post("/validations", json=payload)
    second_response = await client.post("/validations", json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": "Lote 'lote_duplicado' ja existe."}


async def test_get_validation_batch_returns_404_when_batch_does_not_exist(client):
    response = await client.get("/validations/lote_inexistente")

    assert response.status_code == 404
    assert response.json() == {"detail": "Lote 'lote_inexistente' nao encontrado."}


async def test_call_event_can_confirm_record_and_complete_batch(client):
    payload = {
        "batch_id": "lote_call_confirmed",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    await client.post("/validations/lote_call_confirmed/dispatch")
    batch_response = await client.get("/validations/lote_call_confirmed")
    provider_call_id = batch_response.json()["records"][0]["call_attempts"][0]["provider_call_id"]

    response = await client.post(
        "/validations/lote_call_confirmed/records/1/call-events",
        json={
            "provider_call_id": provider_call_id,
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "Contato confirmou que o numero pertence a empresa.",
            "sentiment": "neutral",
            "duration_seconds": 42,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["business_status"] == "confirmed_by_call"
    assert data["final_status"] == "validated"
    assert data["confirmation_source"] == "voice_call"
    assert data["phone_confirmed"] is True
    assert data["call_attempts"][0]["status"] == "answered"
    assert data["call_attempts"][0]["result"] == "confirmed"

    batch_result = await client.get("/validations/lote_call_confirmed")
    batch_data = batch_result.json()
    assert batch_data["batch_status"] == "completed"


async def test_twilio_status_callback_marks_record_as_not_answered_and_queues_whatsapp(
    client,
    monkeypatch,
):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: True)
    monkeypatch.setattr(
        TwilioVoiceService,
        "create_outbound_call",
        lambda self, **kwargs: TwilioCallDispatchResult(
            provider_call_id="CA999",
            provider_status="queued",
            raw_payload={"sid": "CA999", "status": "queued"},
        ),
    )

    payload = {
        "batch_id": "lote_no_answer",
        "source": "web",
        "records": [build_valid_record()],
    }

    await client.post("/validations", json=payload)
    await client.post("/validations/lote_no_answer/dispatch")

    response = await client.post(
        "/webhooks/twilio/voice/status?batch_id=lote_no_answer&external_id=1&attempt_number=1",
        data={
            "CallSid": "CA999",
            "CallStatus": "no-answer",
            "CallDuration": "0",
        },
    )

    assert response.status_code == 200
    batch_response = await client.get("/validations/lote_no_answer")
    data = batch_response.json()
    assert data["records"][0]["business_status"] == "waiting_whatsapp_reply"
    assert len(data["records"][0]["whatsapp_history"]) == 1


async def test_test_voice_call_start_creates_batch_and_dispatches(client, monkeypatch):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: True)
    monkeypatch.setattr(
        TwilioVoiceService,
        "create_outbound_call",
        lambda self, **kwargs: TwilioCallDispatchResult(
            provider_call_id="CATESTCALL",
            provider_status="queued",
            raw_payload={"sid": "CATESTCALL", "status": "queued"},
        ),
    )

    response = await client.post(
        "/test/voice-call/start",
        json={
            "client_name": "Empresa Exemplo LTDA",
            "cnpj": "11.222.333/0001-81",
            "phone": "11987654321",
            "call_scenario": "failed",
            "fallback_message": "Mensagem de teste",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"].startswith("test_voice_")
    assert data["records"][0]["call_attempts"][0]["provider_call_id"] == "CATESTCALL"
