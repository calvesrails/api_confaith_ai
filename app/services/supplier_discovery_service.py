from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from ..core.memory_store import LocalTestMemoryStore
from ..schemas.request import SupplierDiscoveryRequest
from ..schemas.supplier_discovery import (
    SupplierDiscoveryCandidate,
    SupplierDiscoveryResponse,
)
from .errors import AccessDeniedError, PlatformConfigurationError

logger = logging.getLogger(__name__)


class SupplierDiscoveryService:
    def __init__(
        self,
        *,
        memory_store: LocalTestMemoryStore,
        api_key: str | None,
        model: str,
    ) -> None:
        self.memory_store = memory_store
        self.api_key = api_key
        self.model = model

    async def discover_suppliers(
        self,
        payload: SupplierDiscoveryRequest,
        *,
        account_id: int | None = None,
        download_base_path: str = '/test/supplier-discovery',
        api_key_override: str | None = None,
        allow_mock_fallback: bool = True,
    ) -> SupplierDiscoveryResponse:
        search_id = self._generate_search_id()
        effective_api_key = api_key_override or self.api_key
        if effective_api_key:
            try:
                result = await self._discover_with_openai(
                    search_id=search_id,
                    payload=payload,
                    api_key=effective_api_key,
                    download_base_path=download_base_path,
                )
            except Exception as error:  # pragma: no cover - fallback path for local demo
                provider_error_detail = self._extract_provider_error_detail(error)
                logger.exception(
                    'Falha ao buscar fornecedores com OpenAI | search_id=%s error=%s detail=%s',
                    search_id,
                    error,
                    provider_error_detail,
                )
                if not allow_mock_fallback:
                    raise RuntimeError(
                        f'Falha ao executar supplier discovery com web search. Detalhe do provedor: {provider_error_detail}'
                    ) from error
                self.memory_store.add_log(
                    'supplier_discovery',
                    'Busca web falhou e caiu no modo mock.',
                    {
                        'search_id': search_id,
                        'segment_name': payload.segment_name,
                        'region': payload.region,
                        'error': str(error),
                        'detail': provider_error_detail,
                    },
                )
                result = self._build_mock_response(
                    search_id=search_id,
                    payload=payload,
                    download_base_path=download_base_path,
                    message=(
                        'Busca web indisponivel no momento. Resultado de demonstracao gerado localmente. '
                        f'Detalhe do provedor: {provider_error_detail}'
                    ),
                )
        else:
            if not allow_mock_fallback:
                raise PlatformConfigurationError(
                    'Conta sem credenciais OpenAI configuradas para supplier discovery.'
                )
            self.memory_store.add_log(
                'supplier_discovery',
                'OPENAI_API_KEY ausente; usando resultado mock para demonstracao.',
                {
                    'search_id': search_id,
                    'segment_name': payload.segment_name,
                    'region': payload.region,
                },
            )
            result = self._build_mock_response(
                search_id=search_id,
                payload=payload,
                download_base_path=download_base_path,
                message='OPENAI_API_KEY nao configurada. Resultado de demonstracao gerado localmente.',
            )

        self.memory_store.store_supplier_discovery_run(
            search_id,
            result.model_dump(mode='json'),
            account_id=account_id,
        )
        return result

    def get_discovery_result(
        self,
        search_id: str,
        *,
        account_id: int | None = None,
    ) -> SupplierDiscoveryResponse | None:
        stored = self.memory_store.get_supplier_discovery_run(search_id)
        if stored is None:
            return None

        if 'result' not in stored:
            return SupplierDiscoveryResponse.model_validate(stored)

        stored_account_id = stored.get('account_id')
        if stored_account_id is not None and stored_account_id != account_id:
            raise AccessDeniedError('Token nao autorizado para consultar esta busca de fornecedores.')

        return SupplierDiscoveryResponse.model_validate(stored.get('result') or {})

    async def _discover_with_openai(
        self,
        *,
        search_id: str,
        payload: SupplierDiscoveryRequest,
        api_key: str,
        download_base_path: str,
    ) -> SupplierDiscoveryResponse:
        request_payload = self._build_openai_request(payload)
        self.memory_store.add_log(
            'supplier_discovery',
            'Iniciando busca de fornecedores com web search da OpenAI.',
            {
                'search_id': search_id,
                'segment_name': payload.segment_name,
                'region': payload.region,
                'max_suppliers': payload.max_suppliers,
                'model': self.model,
            },
        )

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                'https://api.openai.com/v1/responses',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json=request_payload,
            )
            if response.is_error:
                logger.error(
                    'OpenAI Responses retornou erro na busca de fornecedores | status_code=%s body=%s',
                    response.status_code,
                    response.text,
                )
            response.raise_for_status()
            raw_response = response.json()

        suppliers = self._extract_suppliers_from_response(raw_response, payload.max_suppliers)
        self.memory_store.add_log(
            'supplier_discovery',
            'Busca de fornecedores concluida com sucesso.',
            {
                'search_id': search_id,
                'segment_name': payload.segment_name,
                'region': payload.region,
                'mode': 'openai_web_search',
                'total_suppliers': len(suppliers),
            },
        )
        return SupplierDiscoveryResponse(
            search_id=search_id,
            mode='openai_web_search',
            segment_name=payload.segment_name,
            region=payload.region,
            callback_phone=payload.callback_phone,
            callback_contact_name=payload.callback_contact_name,
            generated_at=datetime.now(timezone.utc),
            total_suppliers=len(suppliers),
            suppliers=suppliers,
            downloadable_file_url=f'{download_base_path}/{search_id}/results.xlsx',
            message='Busca concluida com a Responses API usando web search.',
        )

    def _build_openai_request(self, payload: SupplierDiscoveryRequest) -> dict[str, Any]:
        region_clause = payload.region or 'Brasil'
        prompt = (
            'Voce esta pesquisando fornecedores brasileiros para prospeccao comercial. '
            f'Encontre ate {payload.max_suppliers} empresas reais do segmento "{payload.segment_name}" '
            f'na regiao "{region_clause}". '
            'Retorne SOMENTE JSON valido com a chave suppliers. '
            'Para cada item, inclua supplier_name, phone, website, city, state, source_urls, discovery_confidence e notes. '
            'Priorize sites oficiais, paginas de contato e diretorios confiaveis. '
            'Se nao encontrar telefone, retorne null. '
            'Em notes, resuma em uma frase curta o indicio de que a empresa atua nesse segmento.'
        )
        full_prompt = (
            'Responda apenas em JSON valido. Nao inclua markdown, comentarios ou texto fora do JSON. '
            'A saida deve ter a forma {"suppliers": [...]} com a chave suppliers obrigatoria. '
            + prompt
        )
        return {
            'model': self.model,
            'tools': [{'type': 'web_search'}],
            'input': full_prompt,
            'max_output_tokens': 1800,
        }

    def _extract_suppliers_from_response(
        self,
        raw_response: dict[str, Any],
        limit: int,
    ) -> list[SupplierDiscoveryCandidate]:
        output_text = self._extract_output_text(raw_response)
        if not output_text:
            raise ValueError('A resposta da OpenAI nao trouxe texto estruturado para a busca.')
        payload = json.loads(self._strip_code_fences(output_text))
        candidate_items = payload.get('suppliers') or payload.get('candidates') or []
        if not isinstance(candidate_items, list):
            raise ValueError('O JSON retornado pela OpenAI nao possui a lista suppliers.')

        discovered_sources = self._extract_urls(raw_response)
        suppliers: list[SupplierDiscoveryCandidate] = []
        for item in candidate_items:
            if not isinstance(item, dict):
                continue
            supplier_name = self._clean_text(item.get('supplier_name') or item.get('name'))
            if not supplier_name:
                continue
            source_urls = self._normalize_source_urls(item.get('source_urls') or item.get('sources'))
            if not source_urls:
                source_urls = discovered_sources[:2]
            confidence = item.get('discovery_confidence')
            if isinstance(confidence, int):
                confidence = float(confidence)
            if not isinstance(confidence, float):
                confidence = None
            suppliers.append(
                SupplierDiscoveryCandidate(
                    supplier_name=supplier_name,
                    phone=self._clean_text(item.get('phone') or item.get('phone_number')),
                    website=self._clean_text(item.get('website')),
                    city=self._clean_text(item.get('city')),
                    state=self._clean_text(item.get('state')),
                    source_urls=source_urls,
                    discovery_confidence=confidence,
                    notes=self._clean_text(item.get('notes') or item.get('summary')),
                )
            )
            if len(suppliers) >= limit:
                break

        return suppliers

    def _extract_provider_error_detail(self, error: Exception) -> str:
        response = getattr(error, 'response', None)
        if response is None:
            return str(error)
        detail = response.text.strip()
        if detail:
            return detail
        return str(error)

    def _build_mock_response(
        self,
        *,
        search_id: str,
        payload: SupplierDiscoveryRequest,
        download_base_path: str,
        message: str,
    ) -> SupplierDiscoveryResponse:
        base_segment = payload.segment_name.strip().title()
        region = payload.region or 'Brasil'
        suppliers = [
            SupplierDiscoveryCandidate(
                supplier_name=f'{base_segment} Forte Distribuicao LTDA',
                phone=None,
                website='https://exemplo-fornecedor-1.com.br',
                city='Ribeirao Preto',
                state='SP',
                source_urls=['https://exemplo-fornecedor-1.com.br'],
                discovery_confidence=0.46,
                notes=f'Resultado mock para demonstracao do segmento {base_segment} em {region}.',
            ),
            SupplierDiscoveryCandidate(
                supplier_name=f'Central {base_segment} Comercial',
                phone=None,
                website='https://exemplo-fornecedor-2.com.br',
                city='Campinas',
                state='SP',
                source_urls=['https://exemplo-fornecedor-2.com.br'],
                discovery_confidence=0.41,
                notes='Resultado mock local. Configure a chave da OpenAI para usar web search real.',
            ),
            SupplierDiscoveryCandidate(
                supplier_name=f'{base_segment} Brasil Supply',
                phone=None,
                website='https://exemplo-fornecedor-3.com.br',
                city='Uberlandia',
                state='MG',
                source_urls=['https://exemplo-fornecedor-3.com.br'],
                discovery_confidence=0.39,
                notes='Estrutura de retorno pronta para demonstracao sem custo de chamada.',
            ),
        ][: payload.max_suppliers]
        return SupplierDiscoveryResponse(
            search_id=search_id,
            mode='mock_fallback',
            segment_name=payload.segment_name,
            region=payload.region,
            callback_phone=payload.callback_phone,
            callback_contact_name=payload.callback_contact_name,
            generated_at=datetime.now(timezone.utc),
            total_suppliers=len(suppliers),
            suppliers=suppliers,
            downloadable_file_url=f'{download_base_path}/{search_id}/results.xlsx',
            message=message,
        )

    def _extract_output_text(self, raw_response: dict[str, Any]) -> str:
        output_text = raw_response.get('output_text')
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        texts: list[str] = []
        for output in raw_response.get('output', []):
            if not isinstance(output, dict) or output.get('type') != 'message':
                continue
            for item in output.get('content', []):
                if not isinstance(item, dict):
                    continue
                if item.get('type') in {'output_text', 'text'}:
                    text = item.get('text') or item.get('value')
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
        return '\n'.join(texts).strip()

    def _extract_urls(self, value: Any) -> list[str]:
        urls: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                url = node.get('url')
                if isinstance(url, str) and url.startswith('http'):
                    urls.append(url)
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(value)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    def _normalize_source_urls(self, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if isinstance(item, dict):
                item = item.get('url')
            if isinstance(item, str) and item.startswith('http'):
                normalized.append(item)
        seen: set[str] = set()
        deduped: list[str] = []
        for item in normalized:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _strip_code_fences(self, value: str) -> str:
        stripped = value.strip()
        if stripped.startswith('```'):
            stripped = re.sub(r'^```(?:json)?', '', stripped).strip()
            stripped = re.sub(r'```$', '', stripped).strip()
        return stripped

    def _clean_text(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _generate_search_id(self) -> str:
        return f'supplier_search_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}_{uuid4().hex[:6]}'
