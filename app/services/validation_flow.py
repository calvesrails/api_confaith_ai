import logging

from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.request import ValidationBatchRequest
from ..schemas.response import ValidationBatchResponse
from .errors import BatchAlreadyExistsError, BatchNotFoundError
from .validation_snapshot_builder import ValidationSnapshotBuilder

logger = logging.getLogger(__name__)


class ValidationFlowService:
    def __init__(
        self,
        snapshot_builder: ValidationSnapshotBuilder,
        batch_repository: ValidationBatchRepository,
    ) -> None:
        self.snapshot_builder = snapshot_builder
        self.batch_repository = batch_repository

    def create_batch(self, payload: ValidationBatchRequest) -> ValidationBatchResponse:
        logger.info(
            "Criando lote de validacao | batch_id=%s source=%s records=%s",
            payload.batch_id,
            payload.source.value,
            len(payload.records),
        )
        if self.batch_repository.exists(payload.batch_id):
            logger.warning("Lote duplicado rejeitado | batch_id=%s", payload.batch_id)
            raise BatchAlreadyExistsError(payload.batch_id)

        batch_snapshot = self.snapshot_builder.build_batch_snapshot(payload)
        logger.info(
            "Snapshot inicial do lote pronto | batch_id=%s batch_status=%s total_records=%s",
            batch_snapshot.batch_id,
            batch_snapshot.batch_status,
            batch_snapshot.total_records,
        )
        return self.batch_repository.create_from_snapshot(batch_snapshot)

    def get_batch(self, batch_id: str) -> ValidationBatchResponse:
        logger.info("Consultando lote de validacao | batch_id=%s", batch_id)
        batch_snapshot = self.batch_repository.get_snapshot_by_batch_id(batch_id)
        if batch_snapshot is None:
            logger.warning("Lote nao encontrado na consulta | batch_id=%s", batch_id)
            raise BatchNotFoundError(batch_id)
        return batch_snapshot
