import logging
from datetime import datetime, timedelta, timezone

from ..db.models import ValidationBatchModel
from ..domain.statuses import BatchStatus, CallResult, CallStatus, FinalStatus
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..schemas.mobile import (
    MobileCallItem,
    MobileCallListResponse,
    MobileDashboardRecordItem,
    MobileDashboardResponse,
    MobileDashboardSummary,
    MobilePeriod,
)
from ..schemas.request import SupplierValidationBatchRequest, ValidationBatchRequest
from ..schemas.response import ValidationBatchResponse
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

    def create_supplier_batch(
        self,
        payload: SupplierValidationBatchRequest,
        *,
        account_id: int | None = None,
        api_token_id: int | None = None,
        caller_company_name: str | None = None,
    ) -> ValidationBatchResponse:
        logger.info(
            "Criando lote de validacao de fornecedor | batch_id=%s source=%s records=%s account_id=%s segment_name=%s",
            payload.batch_id,
            payload.source.value,
            len(payload.records),
            account_id,
            payload.segment_name,
        )
        if self.batch_repository.exists(payload.batch_id, account_id=account_id):
            logger.warning("Lote duplicado rejeitado | batch_id=%s", payload.batch_id)
            raise BatchAlreadyExistsError(payload.batch_id)

        batch_snapshot = self.snapshot_builder.build_supplier_batch_snapshot(
            payload,
            account_id=account_id,
            api_token_id=api_token_id,
            caller_company_name=caller_company_name,
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

    def get_mobile_dashboard(
        self,
        *,
        account_id: int,
        period: MobilePeriod,
    ) -> MobileDashboardResponse:
        logger.info("Montando dashboard mobile | account_id=%s period=%s", account_id, period.value)
        window_start, window_end = self._resolve_mobile_window(period)
        batch_models = self.batch_repository.list_batch_models_for_account(account_id=account_id)
        batches = [self.batch_repository.build_batch_response(batch_model) for batch_model in batch_models]
        call_items = self._build_mobile_call_items(batches, window_start=window_start, window_end=window_end)
        latest_record_attempts = self._select_latest_mobile_record_attempts(call_items, batches)

        confirmed_records: list[MobileDashboardRecordItem] = []
        not_confirmed_records: list[MobileDashboardRecordItem] = []
        not_answered_records: list[MobileDashboardRecordItem] = []

        for (batch_id, _external_id), payload in latest_record_attempts.items():
            record = payload["record"]
            attempt = payload["attempt"]
            item = self._build_mobile_dashboard_record_item(batch_id, record, attempt=attempt)
            if attempt.result == CallResult.CONFIRMED:
                confirmed_records.append(item)
            elif attempt.status == CallStatus.NOT_ANSWERED or attempt.result == CallResult.NOT_ANSWERED:
                not_answered_records.append(item)
            else:
                not_confirmed_records.append(item)

        duration_values = [
            item.duration_seconds
            for item in call_items
            if item.duration_seconds is not None and item.duration_seconds > 0
        ]
        average_call_duration_seconds = round(
            sum(duration_values) / len(duration_values), 1
        ) if duration_values else 0.0
        average_call_cost_estimate_brl = round(
            (average_call_duration_seconds / 60) * 0.10, 2
        ) if average_call_duration_seconds else 0.0

        active_batch_ids = {batch_id for batch_id, _external_id in latest_record_attempts.keys()}
        summary = MobileDashboardSummary(
            total_batches=len(active_batch_ids),
            completed_batches=sum(
                batch.batch_status == BatchStatus.COMPLETED for batch in batches if batch.batch_id in active_batch_ids
            ),
            processing_batches=sum(
                batch.batch_status == BatchStatus.PROCESSING for batch in batches if batch.batch_id in active_batch_ids
            ),
            total_records=len(latest_record_attempts),
            validated_phones=sum(1 for item in confirmed_records if item.validated_phone),
            confirmed_numbers=len(confirmed_records),
            not_confirmed_numbers=len(not_confirmed_records),
            not_answered_numbers=len(not_answered_records),
            average_call_duration_seconds=average_call_duration_seconds,
            average_call_cost_estimate_brl=average_call_cost_estimate_brl,
            total_call_attempts=len(call_items),
        )

        return MobileDashboardResponse(
            period=period,
            window_start=window_start,
            window_end=window_end,
            generated_at=datetime.now(timezone.utc),
            summary=summary,
            confirmed_records=confirmed_records,
            not_confirmed_records=not_confirmed_records,
            not_answered_records=not_answered_records,
        )

    def list_mobile_calls(
        self,
        *,
        account_id: int,
        period: MobilePeriod,
        limit: int = 50,
        offset: int = 0,
    ) -> MobileCallListResponse:
        logger.info(
            "Listando chamadas para mobile | account_id=%s period=%s limit=%s offset=%s",
            account_id,
            period.value,
            limit,
            offset,
        )
        window_start, window_end = self._resolve_mobile_window(period)
        batch_models = self.batch_repository.list_batch_models_for_account(account_id=account_id)
        batches = [self.batch_repository.build_batch_response(batch_model) for batch_model in batch_models]
        items = self._build_mobile_call_items(batches, window_start=window_start, window_end=window_end)
        items.sort(
            key=lambda item: item.started_at or item.finished_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        total = len(items)
        paginated_items = items[offset : offset + limit]
        return MobileCallListResponse(
            period=period,
            window_start=window_start,
            window_end=window_end,
            generated_at=datetime.now(timezone.utc),
            total=total,
            limit=limit,
            offset=offset,
            items=paginated_items,
        )

    def _build_mobile_call_items(
        self,
        batches: list[ValidationBatchResponse],
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[MobileCallItem]:
        items: list[MobileCallItem] = []
        for batch in batches:
            for record in batch.records:
                for attempt in record.call_attempts:
                    attempt_started_at = self._normalize_mobile_datetime(attempt.started_at)
                    attempt_finished_at = self._normalize_mobile_datetime(attempt.finished_at)
                    attempt_reference = attempt_started_at or attempt_finished_at
                    if not self._is_mobile_attempt_in_window(
                        attempt_reference,
                        window_start=window_start,
                        window_end=window_end,
                    ):
                        continue

                    items.append(
                        MobileCallItem(
                            batch_id=batch.batch_id,
                            external_id=record.external_id,
                            client_name=record.client_name,
                            phone_original=record.phone_original,
                            phone_normalized=record.phone_normalized,
                            validated_phone=record.validated_phone,
                            phone_confirmed=record.phone_confirmed,
                            attempt_number=attempt.attempt_number,
                            provider_call_id=attempt.provider_call_id,
                            phone_dialed=attempt.phone_dialed,
                            from_phone_number_used=attempt.from_phone_number_used,
                            phone_source=attempt.phone_source,
                            status=attempt.status,
                            result=attempt.result,
                            duration_seconds=attempt.duration_seconds,
                            started_at=attempt_started_at,
                            finished_at=attempt_finished_at,
                            transcript_summary=attempt.transcript_summary,
                            customer_transcript=attempt.customer_transcript,
                            assistant_transcript=attempt.assistant_transcript,
                            observation=attempt.observation,
                        )
                    )
        return items

    def _resolve_mobile_window(self, period: MobilePeriod) -> tuple[datetime, datetime]:
        window_end = datetime.now(timezone.utc)
        if period == MobilePeriod.LAST_24_HOURS:
            window_start = window_end - timedelta(hours=24)
        elif period == MobilePeriod.WEEK:
            window_start = window_end - timedelta(days=7)
        else:
            window_start = window_end - timedelta(days=30)
        return window_start, window_end

    def _normalize_mobile_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _is_mobile_attempt_in_window(
        self,
        value: datetime | None,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> bool:
        if value is None:
            return False
        return window_start <= value <= window_end

    def _select_latest_mobile_record_attempts(
        self,
        call_items: list[MobileCallItem],
        batches: list[ValidationBatchResponse],
    ) -> dict[tuple[str, str], dict[str, object]]:
        record_lookup = {
            (batch.batch_id, record.external_id): record
            for batch in batches
            for record in batch.records
        }
        latest_map: dict[tuple[str, str], dict[str, object]] = {}

        for item in call_items:
            key = (item.batch_id, item.external_id)
            current = latest_map.get(key)
            current_reference = None
            if current is not None:
                current_attempt = current["attempt"]
                current_reference = current_attempt.started_at or current_attempt.finished_at
            candidate_reference = item.started_at or item.finished_at
            if current_reference is None or (
                candidate_reference is not None and candidate_reference > current_reference
            ):
                latest_map[key] = {
                    "record": record_lookup[key],
                    "attempt": item,
                }

        return latest_map

    def _build_mobile_dashboard_record_item(
        self,
        batch_id: str,
        record,
        *,
        attempt: MobileCallItem | None = None,
    ) -> MobileDashboardRecordItem:
        return MobileDashboardRecordItem(
            batch_id=batch_id,
            external_id=record.external_id,
            client_name=record.client_name,
            phone_original=record.phone_original,
            phone_normalized=record.phone_normalized,
            validated_phone=record.validated_phone,
            last_phone_dialed=(attempt.phone_dialed if attempt is not None and attempt.phone_dialed else record.last_phone_dialed),
            call_status=attempt.status if attempt is not None else record.call_status,
            call_result=attempt.result if attempt is not None else record.call_result,
            business_status=record.business_status,
            final_status=record.final_status,
            phone_confirmed=record.phone_confirmed,
            confirmation_source=record.confirmation_source,
            observation=record.observation,
        )
