from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.session import get_db_session
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..services.registry_lookup import RegistryLookupService
from ..services.validation_flow import ValidationFlowService
from ..services.validation_snapshot_builder import ValidationSnapshotBuilder


async def get_validation_flow_service(
    session: Session = Depends(get_db_session),
) -> ValidationFlowService:
    settings = get_settings()
    registry_lookup_service = RegistryLookupService(settings.known_cnpjs)
    snapshot_builder = ValidationSnapshotBuilder(
        registry_lookup=registry_lookup_service
    )
    batch_repository = ValidationBatchRepository(session=session)
    return ValidationFlowService(
        snapshot_builder=snapshot_builder,
        batch_repository=batch_repository,
    )
