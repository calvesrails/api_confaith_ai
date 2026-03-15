from fastapi import APIRouter

from .routes.health import router as health_router
from .routes.test_ui import router as test_ui_router
from .routes.test_validate import router as test_validate_router
from .routes.twilio_voice import router as twilio_voice_router
from .routes.validations import router as validations_router
from .routes.whatsapp_webhook import router as whatsapp_webhook_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(validations_router)
api_router.include_router(twilio_voice_router)
api_router.include_router(test_ui_router)
api_router.include_router(test_validate_router)
api_router.include_router(whatsapp_webhook_router)
