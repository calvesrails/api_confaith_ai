import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import (
    get_validation_async_service,
    get_validation_flow_service,
)
from ...schemas.async_events import CallEventRequest, WhatsAppEventRequest
from ...schemas.request import ValidationBatchRequest
from ...schemas.response import ValidationBatchResponse, ValidationRecordResponse
from ...services.errors import (
    BatchAlreadyExistsError,
    BatchNotFoundError,
    RecordNotFoundError,
)
from ...services.validation_async_service import ValidationAsyncService
from ...services.validation_flow import ValidationFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validations", tags=["validations"])


@router.post(
    "",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_validation_batch(
    payload: ValidationBatchRequest,
    service: ValidationFlowService = Depends(get_validation_flow_service),
) -> ValidationBatchResponse:
    logger.info(
        "HTTP POST /validations recebido | batch_id=%s source=%s",
        payload.batch_id,
        payload.source.value,
    )
    try:
        return service.create_batch(payload)
    except BatchAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.get(
    "/{batch_id}",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def get_validation_batch(
    batch_id: str,
    service: ValidationFlowService = Depends(get_validation_flow_service),
) -> ValidationBatchResponse:
    logger.info("HTTP GET /validations/{batch_id} recebido | batch_id=%s", batch_id)
    try:
        return service.get_batch(batch_id)
    except BatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post(
    "/{batch_id}/dispatch",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def dispatch_validation_batch(
    batch_id: str,
    twiml_mode: Literal["media_stream", "diagnostic_say"] = Query(
        default="media_stream",
    ),
    service: ValidationAsyncService = Depends(get_validation_async_service),
) -> ValidationBatchResponse:
    logger.info(
        "HTTP POST /validations/{batch_id}/dispatch recebido | batch_id=%s twiml_mode=%s",
        batch_id,
        twiml_mode,
    )
    try:
        return service.dispatch_batch(batch_id, twiml_mode=twiml_mode)
    except BatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post(
    "/{batch_id}/records/{external_id}/call-events",
    response_model=ValidationRecordResponse,
    status_code=status.HTTP_200_OK,
)
async def register_call_event(
    batch_id: str,
    external_id: str,
    payload: CallEventRequest,
    service: ValidationAsyncService = Depends(get_validation_async_service),
) -> ValidationRecordResponse:
    logger.info(
        "HTTP POST call-events recebido | batch_id=%s external_id=%s",
        batch_id,
        external_id,
    )
    try:
        return service.register_call_event(batch_id, external_id, payload)
    except (BatchNotFoundError, RecordNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post(
    "/{batch_id}/records/{external_id}/whatsapp-events",
    response_model=ValidationRecordResponse,
    status_code=status.HTTP_200_OK,
)
async def register_whatsapp_event(
    batch_id: str,
    external_id: str,
    payload: WhatsAppEventRequest,
    service: ValidationAsyncService = Depends(get_validation_async_service),
) -> ValidationRecordResponse:
    logger.info(
        "HTTP POST whatsapp-events recebido | batch_id=%s external_id=%s",
        batch_id,
        external_id,
    )
    try:
        return service.register_whatsapp_event(batch_id, external_id, payload)
    except (BatchNotFoundError, RecordNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
