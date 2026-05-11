"""Health-check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter

from core.config import settings

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_title,
        "version": settings.app_version,
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
