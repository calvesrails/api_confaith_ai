from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, status

from ...schemas.async_events import CallEventRequest
from ...services.errors import ProviderConfigurationError, RealtimeBridgeError
from ...services.openai_realtime_bridge import OpenAIRealtimeBridgeService
from ...services.twilio_voice_service import TwilioVoiceService
from ...services.validation_async_service import ValidationAsyncService
from ..dependencies import (
    get_openai_realtime_bridge_service,
    get_twilio_voice_service,
    get_validation_async_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/twilio/voice", tags=["twilio-voice"])


@router.post("/twiml")
async def get_twiml_for_call(
    request: Request,
    twiml_mode: Literal["media_stream", "diagnostic_say"] = Query(
        default="media_stream",
    ),
    twilio_voice_service: TwilioVoiceService = Depends(get_twilio_voice_service),
) -> Response:
    logger.info("Webhook TwiML do Twilio recebido | twiml_mode=%s", twiml_mode)
    try:
        query = request.query_params
        twiml = twilio_voice_service.build_voice_twiml(
            batch_id=query.get("batch_id", ""),
            external_id=query.get("external_id", ""),
            attempt_number=query.get("attempt_number", "1"),
            caller_company_name=query.get("caller_company_name"),
            client_name=query.get("client_name", "Cliente sem nome"),
            cnpj=query.get("cnpj", ""),
            phone_dialed=query.get("phone_dialed", ""),
            twiml_mode=twiml_mode,
            realtime_model=query.get("realtime_model"),
            realtime_voice=query.get("realtime_voice"),
            realtime_output_speed=query.get("realtime_output_speed"),
            realtime_style_profile=query.get("realtime_style_profile"),
        )
    except ProviderConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return Response(content=twiml, media_type="text/xml")


@router.post("/status")
async def receive_twilio_status_callback(
    request: Request,
    service: ValidationAsyncService = Depends(get_validation_async_service),
) -> Response:
    logger.info("Webhook de status do Twilio recebido")
    form = await request.form()
    query = request.query_params
    call_sid = form.get("CallSid")
    call_status = form.get("CallStatus")
    call_duration = form.get("CallDuration")

    if not isinstance(call_status, str) or not call_status:
        logger.warning("Webhook de status do Twilio sem CallStatus valido")
        return Response(status_code=status.HTTP_200_OK)

    duration_seconds = None
    if isinstance(call_duration, str) and call_duration.isdigit():
        duration_seconds = int(call_duration)

    logger.info(
        "Processando status callback do Twilio | batch_id=%s external_id=%s call_sid=%s call_status=%s",
        query.get("batch_id", ""),
        query.get("external_id", ""),
        call_sid,
        call_status,
    )
    try:
        service.register_twilio_status_callback(
            batch_id=query.get("batch_id", ""),
            external_id=query.get("external_id", ""),
            provider_call_id=call_sid if isinstance(call_sid, str) else None,
            provider_status=call_status,
            duration_seconds=duration_seconds,
        )
    except Exception as error:
        logger.exception("Falha ao processar status callback do Twilio | error=%s", error)
        return Response(status_code=status.HTTP_200_OK)

    return Response(status_code=status.HTTP_200_OK)


@router.websocket("/media-stream")
async def bridge_twilio_media_stream(
    websocket: WebSocket,
    bridge_service: OpenAIRealtimeBridgeService = Depends(get_openai_realtime_bridge_service),
    validation_service: ValidationAsyncService = Depends(get_validation_async_service),
) -> None:
    logger.info("WebSocket de media stream do Twilio conectado")
    try:
        bridge_result = await bridge_service.bridge_media_stream(websocket)
    except (ProviderConfigurationError, RealtimeBridgeError) as error:
        logger.exception("Falha no bridge de media stream | error=%s", error)
        await websocket.close(code=1011)
        return

    logger.info(
        "Resultado final do media stream | batch_id=%s external_id=%s provider_call_id=%s call_status=%s call_result=%s",
        bridge_result.batch_id,
        bridge_result.external_id,
        bridge_result.provider_call_id,
        bridge_result.call_status,
        bridge_result.call_result,
    )
    if (
        bridge_result.batch_id
        and bridge_result.external_id
        and bridge_result.provider_call_id
    ):
        validation_service.register_call_event(
            bridge_result.batch_id,
            bridge_result.external_id,
            CallEventRequest(
                provider_call_id=bridge_result.provider_call_id,
                call_status=bridge_result.call_status,
                call_result=bridge_result.call_result,
                transcript_summary=bridge_result.transcript_summary,
                observation=bridge_result.observation,
            ),
        )
