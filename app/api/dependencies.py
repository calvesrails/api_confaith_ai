from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.memory_store import LocalTestMemoryStore, get_memory_store
from ..db.session import get_db_session
from ..repositories.validation_batch_repository import ValidationBatchRepository
from ..services.call_simulator import CallSimulatorService
from ..services.local_test_flow_service import LocalTestFlowService
from ..services.official_company_registry_service import (
    OfficialCompanyRegistryService,
)
from ..services.openai_realtime_bridge import OpenAIRealtimeBridgeService
from ..services.twilio_voice_service import TwilioVoiceService
from ..services.validation_async_service import ValidationAsyncService
from ..services.validation_flow import ValidationFlowService
from ..services.validation_snapshot_builder import ValidationSnapshotBuilder
from ..services.whatsapp_service import WhatsAppService


async def get_validation_flow_service(
    session: Session = Depends(get_db_session),
) -> ValidationFlowService:
    settings = get_settings()
    official_company_registry = OfficialCompanyRegistryService(
        base_url=settings.cnpj_base_url,
    )
    snapshot_builder = ValidationSnapshotBuilder(
        official_company_registry=official_company_registry,
    )
    batch_repository = ValidationBatchRepository(session=session)
    return ValidationFlowService(
        snapshot_builder=snapshot_builder,
        batch_repository=batch_repository,
    )


async def get_twilio_voice_service() -> TwilioVoiceService:
    settings = get_settings()
    return TwilioVoiceService(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_phone_number=settings.twilio_phone_number,
        webhook_base_url=settings.twilio_webhook_base_url,
    )


async def get_openai_realtime_bridge_service() -> OpenAIRealtimeBridgeService:
    settings = get_settings()
    return OpenAIRealtimeBridgeService(
        api_key=settings.openai_api_key,
        model=settings.openai_realtime_model,
        voice=settings.openai_realtime_voice,
        transcription_model=settings.openai_realtime_transcription_model,
        transcription_prompt=settings.openai_realtime_transcription_prompt,
        noise_reduction_type=settings.openai_realtime_noise_reduction,
        vad_threshold=settings.openai_realtime_vad_threshold,
        vad_prefix_padding_ms=settings.openai_realtime_vad_prefix_padding_ms,
        vad_silence_duration_ms=settings.openai_realtime_vad_silence_duration_ms,
        vad_interrupt_response=settings.openai_realtime_vad_interrupt_response,
    )


async def get_validation_async_service(
    session: Session = Depends(get_db_session),
    twilio_voice_service: TwilioVoiceService = Depends(get_twilio_voice_service),
) -> ValidationAsyncService:
    settings = get_settings()
    batch_repository = ValidationBatchRepository(session=session)
    official_company_registry = OfficialCompanyRegistryService(
        base_url=settings.cnpj_base_url,
    )
    return ValidationAsyncService(
        batch_repository=batch_repository,
        official_company_registry=official_company_registry,
        twilio_voice_service=twilio_voice_service,
    )


async def get_call_simulator_service() -> CallSimulatorService:
    return CallSimulatorService()


async def get_whatsapp_service() -> WhatsAppService:
    settings = get_settings()
    return WhatsAppService(
        access_token=settings.meta_access_token,
        phone_number_id=settings.meta_phone_number_id,
        api_version=settings.meta_api_version,
    )


async def get_local_test_memory_store() -> LocalTestMemoryStore:
    return get_memory_store()


async def get_local_test_flow_service(
    memory_store: LocalTestMemoryStore = Depends(get_local_test_memory_store),
    call_simulator: CallSimulatorService = Depends(get_call_simulator_service),
    whatsapp_service: WhatsAppService = Depends(get_whatsapp_service),
) -> LocalTestFlowService:
    settings = get_settings()
    return LocalTestFlowService(
        memory_store=memory_store,
        call_simulator=call_simulator,
        whatsapp_service=whatsapp_service,
        verify_token=settings.meta_verify_token,
    )
