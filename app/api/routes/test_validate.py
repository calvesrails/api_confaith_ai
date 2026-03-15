from datetime import datetime, timezone
import logging
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from ..dependencies import (
    get_local_test_flow_service,
    get_validation_async_service,
    get_validation_flow_service,
)
from ...schemas.request import ValidationBatchRequest
from ...schemas.response import ValidationBatchResponse
from ...schemas.test_flow import (
    ClearStateResponse,
    LocalTestFlowResponse,
    LocalTestStateResponse,
    LocalValidationRequest,
    ManualWhatsAppSendRequest,
    WhatsAppSendResult,
)
from ...services.local_test_flow_service import LocalTestFlowService
from ...services.validation_async_service import ValidationAsyncService
from ...services.validation_flow import ValidationFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["local-test-flow"])


@router.post("/validate", response_model=LocalTestFlowResponse)
async def simulate_validation(
    payload: LocalValidationRequest,
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> LocalTestFlowResponse:
    logger.info(
        "HTTP POST /test/validate recebido | client_name=%s call_scenario=%s",
        payload.client_name,
        payload.call_scenario,
    )
    return await service.simulate_validation(payload)


@router.post("/voice-call/start", response_model=ValidationBatchResponse)
async def start_real_voice_call(
    payload: LocalValidationRequest,
    twiml_mode: Literal["media_stream", "diagnostic_say"] = Query(
        default="media_stream",
    ),
    validation_flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    validation_async_service: ValidationAsyncService = Depends(get_validation_async_service),
) -> ValidationBatchResponse:
    batch_id = (
        f"test_voice_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"
    )
    logger.info(
        "HTTP POST /test/voice-call/start recebido | batch_id=%s client_name=%s phone=%s twiml_mode=%s",
        batch_id,
        payload.client_name,
        payload.phone,
        twiml_mode,
    )
    batch_request = ValidationBatchRequest.model_validate(
        {
            "batch_id": batch_id,
            "source": "web",
            "records": [
                {
                    "external_id": "1",
                    "client_name": payload.client_name,
                    "cnpj": payload.cnpj,
                    "phone": payload.phone,
                }
            ],
        }
    )
    validation_flow_service.create_batch(batch_request)
    return validation_async_service.dispatch_batch(batch_id, twiml_mode=twiml_mode)


@router.post("/whatsapp/send", response_model=WhatsAppSendResult)
async def send_whatsapp_message(
    payload: ManualWhatsAppSendRequest,
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> WhatsAppSendResult:
    logger.info("HTTP POST /test/whatsapp/send recebido | phone=%s", payload.phone)
    return await service.send_manual_whatsapp(payload)


@router.get("/state", response_model=LocalTestStateResponse)
async def get_local_test_state(
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> LocalTestStateResponse:
    return service.get_state()


@router.post("/logs/clear", response_model=ClearStateResponse)
async def clear_local_test_state(
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> ClearStateResponse:
    logger.info("HTTP POST /test/logs/clear recebido")
    return service.clear_state()
