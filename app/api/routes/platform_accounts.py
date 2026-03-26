import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_platform_account_service
from ...schemas.platform_accounts import (
    ApiTokenCreateRequest,
    ApiTokenCreateResponse,
    CompanyProfileRequest,
    EmailProviderRequest,
    OpenAIProviderRequest,
    PlatformAccountCreateRequest,
    PlatformAccountResponse,
    TwilioProviderRequest,
)
from ...services.errors import (
    PlatformAccountNotFoundError,
    PlatformAuthenticationError,
    PlatformConfigurationError,
)
from ...services.platform_account_service import PlatformAccountService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform/accounts", tags=["platform-accounts"])


@router.post(
    "",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_account(
    payload: PlatformAccountCreateRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    logger.info(
        "HTTP POST /platform/accounts recebido | external_account_id=%s company_name=%s",
        payload.external_account_id,
        payload.company_name,
    )
    return service.create_account(payload)


@router.get(
    "/{account_id}",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_200_OK,
)
async def get_platform_account(
    account_id: int,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    try:
        return service.get_account(account_id)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/{account_id}/company-profile",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_200_OK,
)
async def update_company_profile(
    account_id: int,
    payload: CompanyProfileRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    try:
        return service.update_company_profile(account_id, payload)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/{account_id}/providers/twilio",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_200_OK,
)
async def update_twilio_provider(
    account_id: int,
    payload: TwilioProviderRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    try:
        return service.update_twilio_provider(account_id, payload)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PlatformConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@router.put(
    "/{account_id}/providers/openai",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_200_OK,
)
async def update_openai_provider(
    account_id: int,
    payload: OpenAIProviderRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    try:
        return service.update_openai_provider(account_id, payload)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/{account_id}/providers/email",
    response_model=PlatformAccountResponse,
    status_code=status.HTTP_200_OK,
)
async def update_email_provider(
    account_id: int,
    payload: EmailProviderRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> PlatformAccountResponse:
    try:
        return service.update_email_provider(account_id, payload)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post(
    "/{account_id}/api-tokens",
    response_model=ApiTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_api_token(
    account_id: int,
    payload: ApiTokenCreateRequest,
    service: PlatformAccountService = Depends(get_platform_account_service),
) -> ApiTokenCreateResponse:
    try:
        return service.create_api_token(account_id, payload)
    except PlatformAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
