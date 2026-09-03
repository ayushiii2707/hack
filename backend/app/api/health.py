"""Health endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "razorpay_configured": settings.razorpay_configured,
        "gemini_configured": settings.gemini_configured,
    }
