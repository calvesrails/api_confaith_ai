from fastapi import APIRouter, Depends, status

from ..dependencies import get_validation_flow_service
from ...schemas.request import ValidationBatchRequest
from ...schemas.response import ValidationBatchResponse
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
    return service.process_batch(payload)
