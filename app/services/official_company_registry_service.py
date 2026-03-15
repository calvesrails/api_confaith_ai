from __future__ import annotations

import logging
from typing import Any

import httpx

from ..utils.strings import only_digits
from .phone import normalize_phone

logger = logging.getLogger(__name__)


class OfficialCompanyRegistryService:
    def __init__(self, *, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def exists(self, cnpj: str | None) -> bool:
        exists = self.fetch_company_data(cnpj) is not None
        logger.info("Resultado consulta CNPJ | cnpj=%s exists=%s", only_digits(cnpj), exists)
        return exists

    def find_alternative_phone(
        self,
        *,
        cnpj: str | None,
        client_name: str,
        excluded_phones: set[str],
    ) -> str | None:
        logger.info(
            "Buscando telefone alternativo na base oficial | cnpj=%s client_name=%s excluded_phones=%s",
            only_digits(cnpj),
            client_name,
            sorted(phone for phone in excluded_phones if phone),
        )
        company_data = self.fetch_company_data(cnpj)
        if company_data is None:
            logger.warning(
                "Base oficial nao retornou dados para telefone alternativo | cnpj=%s",
                only_digits(cnpj),
            )
            return None

        alternative_phone = self._extract_alternative_phone(
            company_data=company_data,
            client_name=client_name,
            excluded_phones=excluded_phones,
        )
        logger.info(
            "Resultado busca de telefone alternativo | cnpj=%s alternative_phone=%s",
            only_digits(cnpj),
            alternative_phone,
        )
        return alternative_phone

    def fetch_company_data(self, cnpj: str | None) -> dict[str, Any] | None:
        normalized_cnpj = only_digits(cnpj)
        if len(normalized_cnpj) != 14:
            logger.warning(
                "Consulta ignorada por CNPJ fora do formato esperado | cnpj=%s",
                normalized_cnpj,
            )
            return None

        logger.info(
            "Consultando BrasilAPI | cnpj=%s url=%s/%s",
            normalized_cnpj,
            self.base_url,
            normalized_cnpj,
        )
        try:
            response = httpx.get(
                f"{self.base_url}/{normalized_cnpj}",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            logger.warning(
                "BrasilAPI respondeu com erro HTTP | cnpj=%s status_code=%s",
                normalized_cnpj,
                error.response.status_code,
            )
            return None
        except httpx.HTTPError as error:
            logger.exception(
                "Falha de rede ao consultar BrasilAPI | cnpj=%s error=%s",
                normalized_cnpj,
                error,
            )
            return None

        payload = response.json()
        if isinstance(payload, dict):
            logger.info(
                "BrasilAPI retornou dados para o CNPJ | cnpj=%s razao_social=%s",
                normalized_cnpj,
                payload.get("razao_social"),
            )
            return payload

        logger.warning(
            "BrasilAPI retornou payload inesperado | cnpj=%s payload_type=%s",
            normalized_cnpj,
            type(payload).__name__,
        )
        return None

    def _extract_alternative_phone(
        self,
        *,
        company_data: dict[str, Any],
        client_name: str,
        excluded_phones: set[str],
    ) -> str | None:
        normalized_excluded_phones = {phone for phone in excluded_phones if phone}
        _ = client_name

        candidate_phones: list[str] = []
        for phone_key in ("ddd_telefone_1", "ddd_telefone_2"):
            phone_value = company_data.get(phone_key)
            if not isinstance(phone_value, str) or not phone_value.strip():
                continue

            normalized_phone = normalize_phone(phone_value)
            if normalized_phone and normalized_phone not in normalized_excluded_phones:
                candidate_phones.append(normalized_phone)

        return candidate_phones[0] if candidate_phones else None
