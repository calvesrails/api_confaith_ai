from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["local-test-ui"])

_templates_directory = Path(__file__).resolve().parents[2] / "templates"


def _read_template(name: str) -> str:
    return (_templates_directory / name).read_text(encoding="utf-8")


@router.get("/test-ui", response_class=HTMLResponse)
async def get_test_ui() -> HTMLResponse:
    return HTMLResponse(content=_read_template("test_ui.html"))


@router.get("/platform-api-ui", response_class=HTMLResponse)
async def get_platform_api_ui() -> HTMLResponse:
    return HTMLResponse(content=_read_template("test_ui.html"))


@router.get("/platform-api-onboarding-ui", response_class=HTMLResponse)
async def get_platform_api_onboarding_ui() -> HTMLResponse:
    return HTMLResponse(content=_read_template("platform_api_ui.html"))
