from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.exception_handlers import register_exception_handlers
from .api.router import api_router
from .core.config import get_settings
from .core.logging import configure_logging
from .db.session import initialize_database


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug_enabled=settings.app_debug)
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    initialize_database()
    register_exception_handlers(app)
    static_directory = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_directory), name="static")
    app.include_router(api_router)
    return app


app = create_app()
