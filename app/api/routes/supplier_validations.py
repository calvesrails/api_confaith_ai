import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..dependencies import (
    get_platform_account_service,
    get_validation_async_service,
    get_validation_flow_service,
)
from ...schemas.request import Source, SupplierValidationBatchRequest
from ...schemas.response import ValidationBatchResponse
from ...services.errors import (
    AccessDeniedError,
    BatchAlreadyExistsError,
    BatchNotFoundError,
    PlatformAuthenticationError,
    PlatformConfigurationError,
)
from ...services.platform_account_service import PlatformAccountService
from ...services.validation_async_service import ValidationAsyncService
from ...services.validation_flow import ValidationFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supplier-validations", tags=["supplier-validations"])


@router.post("", response_model=ValidationBatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_supplier_validation_batch(
    request: Request,
    payload: SupplierValidationBatchRequest,
    flow_service: ValidationFlowService = Depends(get_validation_flow_service),
    async_service: ValidationAsyncService = Depends(get_validation_async_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationBatchResponse:
    logger.info(
        "HTTP POST /supplier-validations recebido | batch_id=%s source=%s segment_name=%s",
        payload.batch_id,
        payload.source.value,
        payload.segment_name,
    )
    account_context = None
    try:
        if payload.source == Source.EXTERNAL:
            account_context = platform_service.authenticate_authorization_header(
                request.headers.get("Authorization")
            )
            platform_service.ensure_account_ready_for_validations(account_context.account)

        batch_response = flow_service.create_supplier_batch(
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except PlatformConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@router.get("/{batch_id}", response_model=ValidationBatchResponse, status_code=status.HTTP_200_OK)
async def get_supplier_validation_batch(
    batch_id: str,
    request: Request,
    service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> ValidationBatchResponse:
    logger.info("HTTP GET /supplier-validations/{batch_id} recebido | batch_id=%s", batch_id)
    auth_header = request.headers.get("Authorization")
    try:
        account_context = platform_service.authenticate_optional_authorization_header(auth_header)
        batch = service.get_batch(
            batch_id,
            account_id=(account_context.account_id if account_context else None),
        )
        if batch.workflow_kind != "supplier_validation":
            raise BatchNotFoundError(batch_id)
        return batch
    except BatchNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(
            status_code=(status.HTTP_401_UNAUTHORIZED if not auth_header else status.HTTP_403_FORBIDDEN),
            detail=str(error),
        ) from error
