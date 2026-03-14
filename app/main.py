from fastapi import FastAPI

from .api.exception_handlers import register_exception_handlers
from .api.router import api_router
from .core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
