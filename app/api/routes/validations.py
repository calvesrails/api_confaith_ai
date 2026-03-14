from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_validation_flow_service
from ...schemas.request import ValidationBatchRequest
from ...schemas.response import ValidationBatchResponse
from ...services.errors import BatchAlreadyExistsError, BatchNotFoundError
from ...services.validation_flow import ValidationFlowService

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
    try:
        return service.get_batch(batch_id)
    except BatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
