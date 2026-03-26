from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["local-test-ui"])

_templates_directory = Path(__file__).resolve().parents[2] / "templates"
_test_template_content = (_templates_directory / "test_ui.html").read_text(encoding="utf-8")
_platform_template_content = (_templates_directory / "platform_api_ui.html").read_text(encoding="utf-8")


@router.get("/test-ui", response_class=HTMLResponse)
async def get_test_ui() -> HTMLResponse:
    return HTMLResponse(content=_test_template_content)


@router.get("/platform-api-ui", response_class=HTMLResponse)
async def get_platform_api_ui() -> HTMLResponse:
    return HTMLResponse(content=_test_template_content)


@router.get("/platform-api-onboarding-ui", response_class=HTMLResponse)
async def get_platform_api_onboarding_ui() -> HTMLResponse:
    return HTMLResponse(content=_platform_template_content)
