from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["local-test-ui"])

_template_path = Path(__file__).resolve().parents[2] / "templates" / "test_ui.html"
_template_content = _template_path.read_text(encoding="utf-8")


@router.get("/test-ui", response_class=HTMLResponse)
async def get_test_ui() -> HTMLResponse:
    return HTMLResponse(content=_template_content)
