import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..dependencies import get_platform_account_service, get_validation_flow_service
from ...schemas.mobile import MobileCallListResponse, MobileDashboardResponse, MobilePeriod
from ...services.errors import PlatformAuthenticationError
from ...services.platform_account_service import PlatformAccountService
from ...services.validation_flow import ValidationFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get(
    "/dashboard",
    response_model=MobileDashboardResponse,
    status_code=status.HTTP_200_OK,
)
async def get_mobile_dashboard(
    request: Request,
    period: MobilePeriod = Query(..., description="Periodo do dashboard: 24h, week ou month."),
    service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> MobileDashboardResponse:
    logger.info("HTTP GET /mobile/dashboard recebido | period=%s", period.value)
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get("Authorization")
        )
        return service.get_mobile_dashboard(
            account_id=account_context.account_id,
            period=period,
        )
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error


@router.get(
    "/calls",
    response_model=MobileCallListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_mobile_calls(
    request: Request,
    period: MobilePeriod = Query(..., description="Periodo das chamadas: 24h, week ou month."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ValidationFlowService = Depends(get_validation_flow_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> MobileCallListResponse:
    logger.info(
        "HTTP GET /mobile/calls recebido | period=%s limit=%s offset=%s",
        period.value,
        limit,
        offset,
    )
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get("Authorization")
        )
        return service.list_mobile_calls(
            account_id=account_context.account_id,
            period=period,
            limit=limit,
            offset=offset,
        )
    except PlatformAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
