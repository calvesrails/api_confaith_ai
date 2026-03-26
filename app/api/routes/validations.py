import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..dependencies import (
    get_platform_account_service,
    get_validation_async_service,
    get_validation_flow_service,
)
from ...schemas.async_events import CallEventRequest, WhatsAppEventRequest
from ...schemas.request import Source, ValidationBatchRequest
from ...schemas.response import ValidationBatchResponse, ValidationRecordResponse
from ...services.errors import (
    AccessDeniedError,
    BatchAlreadyExistsError,
    BatchNotFoundError,
    PlatformAuthenticationError,
    PlatformConfigurationError,
    RecordNotFoundError,
)
from ...services.platform_account_service import PlatformAccountService
from ...services.validation_async_service import ValidationAsyncService
from ...services.validation_flow import ValidationFlowService
from ...domain.statuses import BatchStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validations", tags=["validations"])


@router.get(
    "",
    response_model=list[ValidationBatchResponse],
    status_code=status.HTTP_200_OK,
)
async def list_validation_batches(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    batch_status: BatchStatus | None = Query(default=None),
    service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> list[ValidationBatchResponse]:
    logger.info(
        "HTTP GET /validations recebido | limit=%s offset=%s batch_status=%s",
        limit,
        offset,
        batch_status.value if batch_status is not None else None,
    )
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get("Authorization")
        )
        return service.list_batches(
            account_id=account_context.account_id,
            limit=limit,
            offset=offset,
            batch_status=batch_status,
        )
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error


@router.post(
    "",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_validation_batch(
    request: Request,
    payload: ValidationBatchRequest,
    flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    async_service: ValidationAsyncService = Depends(get_validation_async_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationBatchResponse:
    logger.info(
        "HTTP POST /validations recebido | batch_id=%s source=%s",
        payload.batch_id,
        payload.source.value,
    )
    account_context = None
    try:
        if payload.source == Source.EXTERNAL:
            account_context = platform_service.authenticate_authorization_header(
                request.headers.get("Authorization")
            )
            platform_service.ensure_account_ready_for_validations(account_context.account)

        batch_response = flow_service.create_batch(
            payload,
            account_id=(account_context.account_id if account_context else None),
            api_token_id=(account_context.api_token_id if account_context else None),
            caller_company_name=(
                account_context.account.spoken_company_name
                or account_context.account.company_name
                if account_context
                else None
            ),
        )
        if account_context is not None:
            return async_service.dispatch_batch(
                batch_response.batch_id,
                account_id=account_context.account_id,
            )
        return batch_response
    except BatchAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except PlatformConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.get(
    "/{batch_id}",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def get_validation_batch(
    batch_id: str,
    request: Request,
    service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationBatchResponse:
    logger.info("HTTP GET /validations/{batch_id} recebido | batch_id=%s", batch_id)
    auth_header = request.headers.get("Authorization")
    try:
        account_context = platform_service.authenticate_optional_authorization_header(auth_header)
        return service.get_batch(
            batch_id,
            account_id=(account_context.account_id if account_context else None),
        )
    except BatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except AccessDeniedError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED if not auth_header else status.HTTP_403_FORBIDDEN
            ),
            detail=str(error),
        ) from error


@router.post(
    "/{batch_id}/dispatch",
    response_model=ValidationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def dispatch_validation_batch(
    batch_id: str,
    request: Request,
    twiml_mode: Literal["media_stream", "diagnostic_say"] = Query(
        default="media_stream",
    ),
    service: ValidationAsyncService = Depends(get_validation_async_service),
    flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationBatchResponse:
    logger.info(
        "HTTP POST /validations/{batch_id}/dispatch recebido | batch_id=%s twiml_mode=%s",
        batch_id,
        twiml_mode,
    )
    auth_header = request.headers.get("Authorization")
    try:
        account_context = platform_service.authenticate_optional_authorization_header(auth_header)
        batch_model = flow_service.get_batch_model_or_raise(
            batch_id,
            account_id=(account_context.account_id if account_context else None),
        )
        return service.dispatch_batch(
            batch_model.batch_id,
            twiml_mode=twiml_mode,
        )
    except BatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except AccessDeniedError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED if not auth_header else status.HTTP_403_FORBIDDEN
            ),
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
    request: Request,
    payload: CallEventRequest,
    service: ValidationAsyncService = Depends(get_validation_async_service),
    flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationRecordResponse:
    logger.info(
        "HTTP POST call-events recebido | batch_id=%s external_id=%s",
        batch_id,
        external_id,
    )
    auth_header = request.headers.get("Authorization")
    try:
        account_context = platform_service.authenticate_optional_authorization_header(auth_header)
        batch_model = flow_service.get_batch_model_or_raise(
            batch_id,
            account_id=(account_context.account_id if account_context else None),
        )
        return service.register_call_event(
            batch_model.batch_id,
            external_id,
            payload,
        )
    except (BatchNotFoundError, RecordNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except AccessDeniedError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED if not auth_header else status.HTTP_403_FORBIDDEN
            ),
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
    request: Request,
    payload: WhatsAppEventRequest,
    service: ValidationAsyncService = Depends(get_validation_async_service),
    flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationRecordResponse:
    logger.info(
        "HTTP POST whatsapp-events recebido | batch_id=%s external_id=%s",
        batch_id,
        external_id,
    )
    auth_header = request.headers.get("Authorization")
    try:
        account_context = platform_service.authenticate_optional_authorization_header(auth_header)
        batch_model = flow_service.get_batch_model_or_raise(
            batch_id,
            account_id=(account_context.account_id if account_context else None),
        )
        return service.register_whatsapp_event(
            batch_model.batch_id,
            external_id,
            payload,
        )
    except (BatchNotFoundError, RecordNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except AccessDeniedError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED if not auth_header else status.HTTP_403_FORBIDDEN
            ),
            detail=str(error),
        ) from error
