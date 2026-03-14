from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.request import ValidationBatchRequest
from ..schemas.response import ValidationBatchResponse
from .errors import BatchAlreadyExistsError, BatchNotFoundError
from .validation_snapshot_builder import ValidationSnapshotBuilder


class ValidationFlowService:
    def __init__(
        self,
        snapshot_builder: ValidationSnapshotBuilder,
        batch_repository: ValidationBatchRepository,
    ) -> None:
        self.snapshot_builder = snapshot_builder
        self.batch_repository = batch_repository

    def create_batch(self, payload: ValidationBatchRequest) -> ValidationBatchResponse:
        if self.batch_repository.exists(payload.batch_id):
            raise BatchAlreadyExistsError(payload.batch_id)

        batch_snapshot = self.snapshot_builder.build_batch_snapshot(payload)
        return self.batch_repository.create_from_snapshot(batch_snapshot)

    def get_batch(self, batch_id: str) -> ValidationBatchResponse:
        batch_snapshot = self.batch_repository.get_snapshot_by_batch_id(batch_id)
        if batch_snapshot is None:
            raise BatchNotFoundError(batch_id)
        return batch_snapshot
