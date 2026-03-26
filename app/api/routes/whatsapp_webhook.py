import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from ..dependencies import get_local_test_flow_service
from ...schemas.test_flow import WebhookReceiveResponse
from ...services.local_test_flow_service import LocalTestFlowService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhook"])


@router.get("/webhooks/whatsapp/meta", response_class=PlainTextResponse)
async def verify_meta_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> PlainTextResponse:
    logger.info(
        "Webhook GET da Meta recebido | hub_mode=%s hub_verify_token_present=%s",
        hub_mode,
        hub_verify_token is not None,
    )
    if not service.verify_webhook(hub_mode, hub_verify_token, hub_challenge):
        logger.warning("Falha na verificacao do webhook da Meta")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook verification failed.",
        )

    logger.info("Webhook da Meta validado com sucesso")
    return PlainTextResponse(hub_challenge or "")


@router.post("/webhooks/whatsapp/meta", response_model=WebhookReceiveResponse)
async def receive_meta_webhook(
    payload: dict[str, Any],
    service: LocalTestFlowService = Depends(get_local_test_flow_service),
) -> WebhookReceiveResponse:
    logger.info("Webhook POST da Meta recebido")
    return service.process_webhook_payload(payload)
