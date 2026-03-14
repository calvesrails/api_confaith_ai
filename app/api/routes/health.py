from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "service": request.app.title,
        "version": request.app.version,
    }
