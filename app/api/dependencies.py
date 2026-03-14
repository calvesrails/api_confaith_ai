from ..core.config import get_settings
from ..services.registry_lookup import RegistryLookupService
from ..services.validation_flow import ValidationFlowService


async def get_validation_flow_service() -> ValidationFlowService:
    settings = get_settings()
    registry_lookup_service = RegistryLookupService(settings.known_cnpjs)
    return ValidationFlowService(registry_lookup=registry_lookup_service)
