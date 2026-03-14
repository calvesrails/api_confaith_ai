from collections.abc import Iterable

from .cnpj import is_valid_cnpj, normalize_cnpj


class RegistryLookupService:
    def __init__(self, known_cnpjs: Iterable[str] | None = None) -> None:
        self.known_cnpjs = {
            normalize_cnpj(cnpj)
            for cnpj in (known_cnpjs or [])
            if normalize_cnpj(cnpj)
        }

    def exists(self, cnpj: str) -> bool:
        normalized_cnpj = normalize_cnpj(cnpj)
        if not is_valid_cnpj(normalized_cnpj):
            return False
        if not self.known_cnpjs:
            return True
        return normalized_cnpj in self.known_cnpjs
