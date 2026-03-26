import logging

from ..db.models import ValidationBatchModel
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.request import ValidationBatchRequest
from ..schemas.response import ValidationBatchResponse
from ..domain.statuses import BatchStatus
from .errors import AccessDeniedError, BatchAlreadyExistsError, BatchNotFoundError
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

    def create_batch(
        self,
        payload: ValidationBatchRequest,
        *,
        account_id: int | None = None,
        api_token_id: int | None = None,
        caller_company_name: str | None = None,
    ) -> ValidationBatchResponse:
        logger.info(
            "Criando lote de validacao | batch_id=%s source=%s records=%s account_id=%s",
            payload.batch_id,
            payload.source.value,
            len(payload.records),
            account_id,
        )
        if self.batch_repository.exists(payload.batch_id, account_id=account_id):
            logger.warning("Lote duplicado rejeitado | batch_id=%s", payload.batch_id)
            raise BatchAlreadyExistsError(payload.batch_id)

        batch_snapshot = self.snapshot_builder.build_batch_snapshot(
            payload,
            account_id=account_id,
            api_token_id=api_token_id,
            caller_company_name=caller_company_name,
        )
        logger.info(
            "Snapshot inicial do lote pronto | batch_id=%s batch_status=%s total_records=%s",
            batch_snapshot.batch_id,
            batch_snapshot.batch_status,
            batch_snapshot.total_records,
        )
        return self.batch_repository.create_from_snapshot(batch_snapshot)

    def get_batch_model_or_raise(
        self,
        batch_id: str,
        *,
        account_id: int | None = None,
    ) -> ValidationBatchModel:
        logger.info("Consultando lote de validacao | batch_id=%s account_id=%s", batch_id, account_id)
        batch_model = None
        if account_id is not None:
            batch_model = self.batch_repository.get_batch_model_for_account(batch_id, account_id)

        if batch_model is None:
            batch_model = self.batch_repository.get_batch_model_for_public_lookup(batch_id)

        if batch_model is None:
            logger.warning("Lote nao encontrado na consulta | batch_id=%s", batch_id)
            raise BatchNotFoundError(batch_id)

        if batch_model.platform_account_id is not None and batch_model.platform_account_id != account_id:
            logger.warning(
                "Acesso negado ao lote | batch_id=%s batch_account_id=%s requested_account_id=%s",
                batch_id,
                batch_model.platform_account_id,
                account_id,
            )
            raise AccessDeniedError("Token nao autorizado para consultar este lote.")

        return batch_model

    def get_batch(
        self,
        batch_id: str,
        *,
        account_id: int | None = None,
    ) -> ValidationBatchResponse:
        batch_model = self.get_batch_model_or_raise(batch_id, account_id=account_id)
        return self.batch_repository.build_batch_response(batch_model)

    def list_batches(
        self,
        *,
        account_id: int,
        limit: int = 20,
        offset: int = 0,
        batch_status: BatchStatus | None = None,
    ) -> list[ValidationBatchResponse]:
        logger.info(
            "Listando lotes da conta | account_id=%s limit=%s offset=%s batch_status=%s",
            account_id,
            limit,
            offset,
            batch_status.value if batch_status is not None else None,
        )
        return self.batch_repository.list_batches(
            account_id=account_id,
            limit=limit,
            offset=offset,
            batch_status=batch_status,
        )
