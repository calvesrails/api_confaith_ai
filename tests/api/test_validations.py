import pytest


pytestmark = pytest.mark.anyio


async def test_create_validation_batch_persists_and_prepares_contact(client):
    payload = {
        "id_lote": "lote_001",
        "origem": "web",
        "records": [
            {
                "id_registro": "1",
                "nome_fornecedor": "Empresa Exemplo LTDA",
                "cnpj": "11.222.333/0001-81",
                "telefone": "(11) 98765-4321",
            },
            {
                "external_id": "2",
                "supplier_name": "Fornecedor Telefone Invalido",
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
    assert data["technical_status"] == "processing"
    assert data["total_records"] == 2
    assert data["summary"] == {
        "ready_for_call": 1,
        "validation_failed": 1,
        "invalid_phone": 1,
        "cnpj_not_found": 0,
        "processing": 1,
    }

    first_record = data["records"][0]
    assert first_record["external_id"] == "1"
    assert first_record["cnpj_normalized"] == "11222333000181"
    assert first_record["phone_normalized"] == "5511987654321"
    assert first_record["phone_type"] == "mobile"
    assert first_record["business_status"] == "ready_for_call"
    assert first_record["call_status"] == "queued"
    assert first_record["call_result"] == "pending_dispatch"
    assert first_record["final_status"] == "processing"

    second_record = data["records"][1]
    assert second_record["phone_normalized"] is None
    assert second_record["phone_valid"] is False
    assert second_record["business_status"] == "invalid_phone"
    assert second_record["final_status"] == "validation_failed"

    persisted_response = await client.get("/validations/lote_001")

    assert persisted_response.status_code == 200
    persisted_data = persisted_response.json()
    assert persisted_data["batch_id"] == "lote_001"
    assert persisted_data["summary"] == data["summary"]
    assert persisted_data["records"][0]["call_status"] == "queued"
    assert persisted_data["records"][1]["business_status"] == "invalid_phone"


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
        "records": [
            {
                "external_id": "1",
                "supplier_name": "Empresa Exemplo LTDA",
                "cnpj": "11.222.333/0001-81",
                "phone": "11987654321",
            }
        ],
    }

    first_response = await client.post("/validations", json=payload)
    second_response = await client.post("/validations", json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Lote 'lote_duplicado' ja existe."
    }


async def test_get_validation_batch_returns_404_when_batch_does_not_exist(client):
    response = await client.get("/validations/lote_inexistente")

    assert response.status_code == 404
    assert response.json() == {"detail": "Lote 'lote_inexistente' nao encontrado."}
