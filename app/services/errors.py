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
    def __init__(self, provider_name: str, message: str) -> None:
        super().__init__(f"Falha ao chamar {provider_name}: {message}")


class RealtimeBridgeError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
