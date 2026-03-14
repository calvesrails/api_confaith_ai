class BatchAlreadyExistsError(Exception):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"Lote '{batch_id}' ja existe.")


class BatchNotFoundError(Exception):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"Lote '{batch_id}' nao encontrado.")
