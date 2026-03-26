from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.schemas.email_delivery import EmailSendResult
from app.services.email_service import EmailService
from app.services.twilio_voice_service import TwilioCallDispatchResult, TwilioVoiceService

pytestmark = pytest.mark.anyio

ADMIN_HEADERS = {"X-Platform-Admin-Key": "test-platform-admin-key"}


def build_external_record(external_id: str) -> dict:
    return {
        "external_id": external_id,
        "client_name": f"Fornecedor {external_id} LTDA",
        "cnpj": "11.222.333/0001-81",
        "phone": "11987654321",
        "email": f"contato{external_id}@fornecedor.com.br",
    }


async def create_ready_platform_account(client, *, external_account_id: str, company_name: str, spoken_company_name: str):
    account_response = await client.post(
        "/platform/accounts",
        headers=ADMIN_HEADERS,
        json={
            "external_account_id": external_account_id,
            "company_name": company_name,
            "spoken_company_name": spoken_company_name,
            "owner_name": "Caio Alves",
            "owner_email": "caio@example.com",
        },
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]

    twilio_response = await client.put(
        f"/platform/accounts/{account_id}/providers/twilio",
        headers=ADMIN_HEADERS,
        json={
            "account_sid": f"AC{external_account_id[-4:]:0>4}",
            "auth_token": "twilio-secret",
            "webhook_base_url": "https://example.ngrok-free.app",
            "phone_numbers": [
                {
                    "phone_number": "11999990000",
                    "friendly_name": "Linha 1",
                    "is_active": True,
                    "max_concurrent_calls": 1,
                },
                {
                    "phone_number": "11999990001",
                    "friendly_name": "Linha 2",
                    "is_active": True,
                    "max_concurrent_calls": 1,
                },
            ],
        },
    )
    assert twilio_response.status_code == 200

    openai_response = await client.put(
        f"/platform/accounts/{account_id}/providers/openai",
        headers=ADMIN_HEADERS,
        json={
            "api_key": "sk-account-openai-key",
            "realtime_model": "gpt-realtime-1.5",
            "realtime_voice": "cedar",
            "realtime_output_speed": 0.93,
            "realtime_style_instructions": "Fale como uma atendente brasileira natural e cordial.",
        },
    )
    assert openai_response.status_code == 200

    email_response = await client.put(
        f"/platform/accounts/{account_id}/providers/email",
        headers=ADMIN_HEADERS,
        json={
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "validacao@example.com",
            "smtp_password": "smtp-secret",
            "smtp_use_tls": True,
            "from_address": "validacao@example.com",
            "from_name": spoken_company_name,
        },
    )
    assert email_response.status_code == 200

    token_response = await client.post(
        f"/platform/accounts/{account_id}/api-tokens",
        headers=ADMIN_HEADERS,
        json={"name": "default"},
    )
    assert token_response.status_code == 201
    return account_id, token_response.json()["raw_token"]


async def test_platform_account_endpoints_create_and_mask_provider_configs(client):
    account_id, raw_token = await create_ready_platform_account(
        client,
        external_account_id="rails_account_001",
        company_name="XPTO Assessoria LTDA",
        spoken_company_name="XPTO Validacao",
    )

    account_response = await client.get(
        f"/platform/accounts/{account_id}",
        headers=ADMIN_HEADERS,
    )

    assert account_response.status_code == 200
    data = account_response.json()
    assert data["id"] == account_id
    assert data["caller_company_name"] == "XPTO Validacao"
    assert data["active_api_tokens"] == 1
    assert data["twilio"]["configured"] is True
    assert data["twilio"]["active_phone_numbers"] == 2
    assert len(data["twilio"]["phone_numbers"]) == 2
    assert data["openai"]["configured"] is True
    assert data["openai"]["realtime_model"] == "gpt-realtime-1.5"
    assert data["email"]["configured"] is True
    assert raw_token.startswith("tkn_live_")
    assert "***" in data["twilio"]["account_sid_masked"]
    assert "***" in data["openai"]["api_key_masked"]


async def test_creating_new_api_token_revokes_previous_token(client):
    account_response = await client.post(
        "/platform/accounts",
        headers=ADMIN_HEADERS,
        json={
            "external_account_id": "rails_account_token_rotation",
            "company_name": "Conta Token LTDA",
            "spoken_company_name": "Conta Token",
            "owner_name": "Caio Alves",
            "owner_email": "caio@example.com",
        },
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]

    first_token_response = await client.post(
        f"/platform/accounts/{account_id}/api-tokens",
        headers=ADMIN_HEADERS,
        json={"name": "first-token"},
    )
    assert first_token_response.status_code == 201
    first_raw_token = first_token_response.json()["raw_token"]

    second_token_response = await client.post(
        f"/platform/accounts/{account_id}/api-tokens",
        headers=ADMIN_HEADERS,
        json={"name": "second-token"},
    )
    assert second_token_response.status_code == 201
    second_raw_token = second_token_response.json()["raw_token"]

    first_auth_response = await client.get(
        "/validations/batch_that_does_not_exist",
        headers={"Authorization": f"Bearer {first_raw_token}"},
    )
    second_auth_response = await client.get(
        "/validations/batch_that_does_not_exist",
        headers={"Authorization": f"Bearer {second_raw_token}"},
    )
    account_snapshot = await client.get(f"/platform/accounts/{account_id}", headers=ADMIN_HEADERS)

    assert first_auth_response.status_code == 401
    assert second_auth_response.status_code == 404
    assert account_snapshot.status_code == 200
    assert account_snapshot.json()["active_api_tokens"] == 1


async def test_external_token_with_naive_expiration_does_not_break_authentication(client):
    account_response = await client.post(
        "/platform/accounts",
        headers=ADMIN_HEADERS,
        json={
            "external_account_id": "rails_account_naive_expiration",
            "company_name": "Conta Naive LTDA",
            "spoken_company_name": "Conta Naive",
            "owner_name": "Caio Alves",
            "owner_email": "caio@example.com",
        },
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]

    token_response = await client.post(
        f"/platform/accounts/{account_id}/api-tokens",
        headers=ADMIN_HEADERS,
        json={
            "name": "naive-expiration",
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).replace(microsecond=0).isoformat(),
        },
    )
    assert token_response.status_code == 201
    raw_token = token_response.json()["raw_token"]

    response = await client.get(
        "/validations/batch_that_does_not_exist",
        headers={"Authorization": f"Bearer {raw_token}"},
    )

    assert response.status_code == 404


async def test_external_batch_requires_bearer_token(client):
    response = await client.post(
        "/validations",
        json={
            "batch_id": "external_without_token",
            "source": "integracao_externa",
            "records": [build_external_record("1")],
        },
    )

    assert response.status_code == 401




async def test_external_batch_id_is_scoped_per_account(client, monkeypatch):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: False)

    _, first_token = await create_ready_platform_account(
        client,
        external_account_id="rails_account_scope_a",
        company_name="Conta A LTDA",
        spoken_company_name="Conta A",
    )
    _, second_token = await create_ready_platform_account(
        client,
        external_account_id="rails_account_scope_b",
        company_name="Conta B LTDA",
        spoken_company_name="Conta B",
    )

    shared_batch_id = "external_shared_batch_id"

    first_create = await client.post(
        "/validations",
        headers={"Authorization": f"Bearer {first_token}"},
        json={
            "batch_id": shared_batch_id,
            "source": "integracao_externa",
            "records": [build_external_record("1")],
        },
    )
    second_create = await client.post(
        "/validations",
        headers={"Authorization": f"Bearer {second_token}"},
        json={
            "batch_id": shared_batch_id,
            "source": "integracao_externa",
            "records": [build_external_record("2")],
        },
    )

    assert first_create.status_code == 202
    assert second_create.status_code == 202
    assert first_create.json()["batch_id"] == shared_batch_id
    assert second_create.json()["batch_id"] == shared_batch_id

    first_batches = await client.get(
        "/validations",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second_batches = await client.get(
        "/validations",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first_batches.status_code == 200
    assert second_batches.status_code == 200
    assert [batch["batch_id"] for batch in first_batches.json()] == [shared_batch_id]
    assert [batch["batch_id"] for batch in second_batches.json()] == [shared_batch_id]

    first_batch = await client.get(
        f"/validations/{shared_batch_id}",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second_batch = await client.get(
        f"/validations/{shared_batch_id}",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first_batch.status_code == 200
    assert second_batch.status_code == 200
    assert first_batch.json()["records"][0]["external_id"] == "1"
    assert second_batch.json()["records"][0]["external_id"] == "2"

async def test_external_batch_uses_account_configuration_and_restricts_batch_access(client, monkeypatch):
    dispatched_calls: list[dict[str, object]] = []

    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: True)

    def fake_create_outbound_call(self, **kwargs) -> TwilioCallDispatchResult:
        dispatched_calls.append(dict(kwargs))
        provider_call_id = f"CA_EXT_{kwargs['external_id']}_{kwargs['attempt_number']}"
        return TwilioCallDispatchResult(
            provider_call_id=provider_call_id,
            provider_status="queued",
            raw_payload={"sid": provider_call_id, "status": "queued"},
        )

    monkeypatch.setattr(TwilioVoiceService, "create_outbound_call", fake_create_outbound_call)

    account_id, raw_token = await create_ready_platform_account(
        client,
        external_account_id="rails_account_002",
        company_name="XPTO Cliente LTDA",
        spoken_company_name="XPTO Validacao",
    )
    _, other_token = await create_ready_platform_account(
        client,
        external_account_id="rails_account_003",
        company_name="Outra Conta LTDA",
        spoken_company_name="Outra Conta",
    )

    headers = {"Authorization": f"Bearer {raw_token}"}
    create_response = await client.post(
        "/validations",
        headers=headers,
        json={
            "batch_id": "external_batch_account_pool",
            "source": "integracao_externa",
            "records": [
                build_external_record("1"),
                build_external_record("2"),
                build_external_record("3"),
            ],
        },
    )

    assert create_response.status_code == 202
    data = create_response.json()
    assert data["account_id"] == account_id
    assert data["caller_company_name"] == "XPTO Validacao"
    assert len(dispatched_calls) == 2
    assert {call["from_phone_number_override"] for call in dispatched_calls} == {
        "5511999990000",
        "5511999990001",
    }
    assert all(call["caller_company_name"] == "XPTO Validacao" for call in dispatched_calls)

    unauthorized_response = await client.get("/validations/external_batch_account_pool")
    assert unauthorized_response.status_code == 401

    forbidden_response = await client.get(
        "/validations/external_batch_account_pool",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden_response.status_code == 403

    batch_response = await client.get("/validations/external_batch_account_pool", headers=headers)
    assert batch_response.status_code == 200
    batch_data = batch_response.json()
    assert batch_data["records"][0]["call_attempts"][0]["from_phone_number_used"] == "5511999990000"
    assert batch_data["records"][1]["call_attempts"][0]["from_phone_number_used"] == "5511999990001"
    assert batch_data["records"][2]["call_attempts"][0]["provider_call_id"].startswith("call_")

    first_call_id = "CA_EXT_1_1"
    unauthorized_call_event = await client.post(
        "/validations/external_batch_account_pool/records/1/call-events",
        json={
            "provider_call_id": first_call_id,
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "cliente: sim | agente: validacao concluida",
            "duration_seconds": 18,
        },
    )
    assert unauthorized_call_event.status_code == 401

    forbidden_call_event = await client.post(
        "/validations/external_batch_account_pool/records/1/call-events",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "provider_call_id": first_call_id,
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "cliente: sim | agente: validacao concluida",
            "duration_seconds": 18,
        },
    )
    assert forbidden_call_event.status_code == 403

    call_event_response = await client.post(
        "/validations/external_batch_account_pool/records/1/call-events",
        headers=headers,
        json={
            "provider_call_id": first_call_id,
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "cliente: sim | agente: validacao concluida",
            "duration_seconds": 18,
        },
    )

    assert call_event_response.status_code == 200
    assert len(dispatched_calls) == 3
    assert dispatched_calls[2]["external_id"] == "3"
    assert dispatched_calls[2]["from_phone_number_override"] == "5511999990000"


async def test_list_external_batches_is_scoped_by_token(client, monkeypatch):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: True)

    def fake_create_outbound_call(self, **kwargs) -> TwilioCallDispatchResult:
        provider_call_id = f"CA_LIST_{kwargs['external_id']}_{kwargs['attempt_number']}"
        return TwilioCallDispatchResult(
            provider_call_id=provider_call_id,
            provider_status="queued",
            raw_payload={"sid": provider_call_id, "status": "queued"},
        )

    monkeypatch.setattr(TwilioVoiceService, "create_outbound_call", fake_create_outbound_call)

    _, token_a = await create_ready_platform_account(
        client,
        external_account_id="rails_account_list_001",
        company_name="Conta Lista A LTDA",
        spoken_company_name="Conta Lista A",
    )
    _, token_b = await create_ready_platform_account(
        client,
        external_account_id="rails_account_list_002",
        company_name="Conta Lista B LTDA",
        spoken_company_name="Conta Lista B",
    )

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    for batch_id in ("external_list_a_1", "external_list_a_2"):
        response = await client.post(
            "/validations",
            headers=headers_a,
            json={
                "batch_id": batch_id,
                "source": "integracao_externa",
                "records": [build_external_record(batch_id[-1])],
            },
        )
        assert response.status_code == 202

    response = await client.post(
        "/validations",
        headers=headers_b,
        json={
            "batch_id": "external_list_b_1",
            "source": "integracao_externa",
            "records": [build_external_record("9")],
        },
    )
    assert response.status_code == 202

    unauthorized_response = await client.get("/validations")
    assert unauthorized_response.status_code == 401

    list_response_a = await client.get("/validations", headers=headers_a)
    assert list_response_a.status_code == 200
    data_a = list_response_a.json()
    assert {batch["batch_id"] for batch in data_a} == {"external_list_a_1", "external_list_a_2"}

    list_response_b = await client.get("/validations", headers=headers_b)
    assert list_response_b.status_code == 200
    data_b = list_response_b.json()
    assert [batch["batch_id"] for batch in data_b] == ["external_list_b_1"]


async def test_mobile_dashboard_and_calls_are_scoped_by_token(client, monkeypatch):
    monkeypatch.setattr(TwilioVoiceService, "is_configured", lambda self: False)

    def fake_send_validation_fallback_email(self, **kwargs):
        return EmailSendResult(
            success=True,
            provider_message_id="email_mobile_test",
            subject="Validacao cadastral",
            message_body="Mensagem de teste",
        )

    monkeypatch.setattr(
        EmailService,
        "send_validation_fallback_email",
        fake_send_validation_fallback_email,
    )

    _, token_a = await create_ready_platform_account(
        client,
        external_account_id="rails_account_mobile_001",
        company_name="Conta Mobile A LTDA",
        spoken_company_name="Conta Mobile A",
    )
    _, token_b = await create_ready_platform_account(
        client,
        external_account_id="rails_account_mobile_002",
        company_name="Conta Mobile B LTDA",
        spoken_company_name="Conta Mobile B",
    )

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    create_response = await client.post(
        "/validations",
        headers=headers_a,
        json={
            "batch_id": "mobile_dashboard_batch",
            "source": "integracao_externa",
            "records": [
                build_external_record("1"),
                build_external_record("2"),
                build_external_record("3"),
            ],
        },
    )
    assert create_response.status_code == 202

    confirmed_event = await client.post(
        "/validations/mobile_dashboard_batch/records/1/call-events",
        headers=headers_a,
        json={
            "provider_call_id": "CA_MOBILE_1",
            "call_status": "answered",
            "call_result": "confirmed",
            "transcript_summary": "cliente: sim | agente: validacao concluida",
            "duration_seconds": 22,
        },
    )
    assert confirmed_event.status_code == 200

    rejected_event = await client.post(
        "/validations/mobile_dashboard_batch/records/2/call-events",
        headers=headers_a,
        json={
            "provider_call_id": "CA_MOBILE_2",
            "call_status": "answered",
            "call_result": "rejected",
            "transcript_summary": "cliente: nao e da empresa | agente: obrigada pela informacao",
            "duration_seconds": 18,
        },
    )
    assert rejected_event.status_code == 200

    not_answered_event = await client.post(
        "/validations/mobile_dashboard_batch/records/3/call-events",
        headers=headers_a,
        json={
            "provider_call_id": "CA_MOBILE_3",
            "call_status": "not_answered",
            "call_result": "not_answered",
            "transcript_summary": "Ligacao nao atendida.",
            "duration_seconds": 0,
        },
    )
    assert not_answered_event.status_code == 200

    dashboard_unauthorized = await client.get("/mobile/dashboard?period=month")
    assert dashboard_unauthorized.status_code == 401

    dashboard_other_account = await client.get("/mobile/dashboard?period=month", headers=headers_b)
    assert dashboard_other_account.status_code == 200
    assert dashboard_other_account.json()["summary"]["total_batches"] == 0

    dashboard_response = await client.get("/mobile/dashboard?period=month", headers=headers_a)
    assert dashboard_response.status_code == 200
    dashboard_data = dashboard_response.json()
    assert dashboard_data["period"] == "month"
    assert dashboard_data["summary"] == {
        "total_batches": 1,
        "completed_batches": 0,
        "processing_batches": 1,
        "total_records": 3,
        "validated_phones": 1,
        "confirmed_numbers": 1,
        "not_confirmed_numbers": 1,
        "not_answered_numbers": 1,
        "average_call_duration_seconds": 20.0,
        "average_call_cost_estimate_brl": 0.03,
        "total_call_attempts": 3,
    }
    assert dashboard_data["confirmed_records"][0]["external_id"] == "1"
    assert dashboard_data["confirmed_records"][0]["validated_phone"] == "5511987654321"
    assert dashboard_data["not_confirmed_records"][0]["external_id"] == "2"
    assert dashboard_data["not_answered_records"][0]["external_id"] == "3"

    calls_response = await client.get("/mobile/calls?period=month", headers=headers_a)
    assert calls_response.status_code == 200
    calls_data = calls_response.json()
    assert calls_data["period"] == "month"
    assert calls_data["total"] == 3
    assert [item["provider_call_id"] for item in calls_data["items"]] == [
        "CA_MOBILE_3",
        "CA_MOBILE_2",
        "CA_MOBILE_1",
    ]
    assert calls_data["items"][0]["client_name"] == "Fornecedor 3 LTDA"
    assert calls_data["items"][2]["phone_confirmed"] is True

    calls_paginated = await client.get("/mobile/calls?period=month&limit=2&offset=1", headers=headers_a)
    assert calls_paginated.status_code == 200
    paginated_data = calls_paginated.json()
    assert paginated_data["total"] == 3
    assert len(paginated_data["items"]) == 2
    assert [item["provider_call_id"] for item in paginated_data["items"]] == [
        "CA_MOBILE_2",
        "CA_MOBILE_1",
    ]
