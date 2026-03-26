from __future__ import annotations

import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from ..dependencies import get_platform_account_service, get_supplier_discovery_service
from ...schemas.request import SupplierDiscoveryRequest
from ...schemas.supplier_discovery import SupplierDiscoveryResponse
from ...services.errors import AccessDeniedError, PlatformAuthenticationError, PlatformConfigurationError
from ...services.platform_account_service import PlatformAccountService
from ...services.supplier_discovery_service import SupplierDiscoveryService
from ...utils.security import decrypt_provider_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/supplier-discovery', tags=['supplier-discovery'])


@router.post('', response_model=SupplierDiscoveryResponse, status_code=status.HTTP_200_OK)
async def create_supplier_discovery_search(
    request: Request,
    payload: SupplierDiscoveryRequest,
    service: SupplierDiscoveryService = Depends(get_supplier_discovery_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> SupplierDiscoveryResponse:
    logger.info(
        'HTTP POST /supplier-discovery recebido | segment_name=%s region=%s max_suppliers=%s',
        payload.segment_name,
        payload.region,
        payload.max_suppliers,
    )
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get('Authorization')
        )
        if account_context.account.openai_credential is None:
            raise PlatformConfigurationError(
                'Conta sem credenciais OpenAI configuradas para supplier discovery.'
            )
        api_key = decrypt_provider_secret(account_context.account.openai_credential.api_key)
        return await service.discover_suppliers(
            payload,
            account_id=account_context.account_id,
            download_base_path='/supplier-discovery',
            api_key_override=api_key,
            allow_mock_fallback=False,
        )
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except PlatformConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.get('/{search_id}', response_model=SupplierDiscoveryResponse, status_code=status.HTTP_200_OK)
async def get_supplier_discovery_search(
    search_id: str,
    request: Request,
    service: SupplierDiscoveryService = Depends(get_supplier_discovery_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> SupplierDiscoveryResponse:
    logger.info('HTTP GET /supplier-discovery/{search_id} recebido | search_id=%s', search_id)
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get('Authorization')
        )
        search_result = service.get_discovery_result(search_id, account_id=account_context.account_id)
        if search_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Busca de fornecedores nao encontrada.',
            )
        return search_result
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.get('/{search_id}/results.xlsx')
async def download_supplier_discovery_results(
    search_id: str,
    request: Request,
    service: SupplierDiscoveryService = Depends(get_supplier_discovery_service),
    platform_service: PlatformAccountService = Depends(get_platform_account_service),
) -> StreamingResponse:
    logger.info(
        'HTTP GET /supplier-discovery/{search_id}/results.xlsx recebido | search_id=%s',
        search_id,
    )
    try:
        account_context = platform_service.authenticate_authorization_header(
            request.headers.get('Authorization')
        )
        search_result = service.get_discovery_result(search_id, account_id=account_context.account_id)
        if search_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Busca de fornecedores nao encontrada.',
            )
        workbook_bytes = _build_supplier_discovery_workbook(search_result)
        filename = f'{search_id}_fornecedores_encontrados.xlsx'
        return StreamingResponse(
            io.BytesIO(workbook_bytes),
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    except PlatformAuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


def _build_supplier_discovery_workbook(search_result: SupplierDiscoveryResponse) -> bytes:
    workbook = Workbook()

    results_sheet = workbook.active
    results_sheet.title = 'Fornecedores'
    results_sheet.append([
        'search_id',
        'segment_name',
        'region',
        'supplier_name',
        'phone',
        'website',
        'city',
        'state',
        'source_urls',
        'discovery_confidence',
        'notes',
        'callback_phone',
        'callback_contact_name',
    ])

    for supplier in search_result.suppliers:
        results_sheet.append([
            search_result.search_id,
            search_result.segment_name,
            search_result.region,
            supplier.supplier_name,
            supplier.phone,
            supplier.website,
            supplier.city,
            supplier.state,
            ' | '.join(supplier.source_urls),
            supplier.discovery_confidence,
            supplier.notes,
            search_result.callback_phone,
            search_result.callback_contact_name,
        ])

    summary_sheet = workbook.create_sheet(title='Resumo')
    summary_sheet.append(['campo', 'valor'])
    summary_sheet.append(['search_id', search_result.search_id])
    summary_sheet.append(['mode', search_result.mode])
    summary_sheet.append(['segment_name', search_result.segment_name])
    summary_sheet.append(['region', search_result.region])
    summary_sheet.append(['generated_at', _format_sheet_value(search_result.generated_at)])
    summary_sheet.append(['total_suppliers', search_result.total_suppliers])
    summary_sheet.append(['callback_phone', search_result.callback_phone])
    summary_sheet.append(['callback_contact_name', search_result.callback_contact_name])
    summary_sheet.append(['downloadable_file_url', search_result.downloadable_file_url])
    summary_sheet.append(['message', search_result.message])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _format_sheet_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
