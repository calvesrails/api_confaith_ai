class BatchAlreadyExistsError(Exception):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"Lote '{batch_id}' ja existe.")


class BatchNotFoundError(Exception):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"Lote '{batch_id}' nao encontrado.")


class RecordNotFoundError(Exception):
    def __init__(self, batch_id: str, external_id: str) -> None:
        super().__init__(
            f"Registro '{external_id}' do lote '{batch_id}' nao encontrado."
        )


class ProviderConfigurationError(Exception):
    def __init__(self, provider_name: str, message: str) -> None:
        super().__init__(f"{provider_name} nao configurado: {message}")


class ProviderRequestError(Exception):
    def __init__(
        self,
        provider_name: str,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.status_code = status_code
        self.provider_code = provider_code
        super().__init__(f"Falha ao chamar {provider_name}: {message}")


class RealtimeBridgeError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class PlatformAccountNotFoundError(Exception):
    def __init__(self, account_id: int) -> None:
        super().__init__(f"Conta operacional '{account_id}' nao encontrada.")


class PlatformAuthenticationError(Exception):
    def __init__(self, message: str = "Token de API invalido ou ausente.") -> None:
        super().__init__(message)


class PlatformConfigurationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class AccessDeniedError(Exception):
    def __init__(self, message: str = "Acesso negado ao recurso solicitado.") -> None:
        super().__init__(message)
