"""Health / readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "razorpay_configured": settings.razorpay_configured,
        "razorpay_webhook_secured": bool(settings.razorpay_webhook_secret),
        "gemini_configured": settings.gemini_configured,
        "admin_configured": settings.admin_configured,
        "demo_endpoints": settings.enable_demo_endpoints,
    }


@router.get("/health/ready", summary="Readiness probe (checks the database)")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    problems = settings.validate_for_environment()
    return {"status": "ready" if not problems else "degraded", "config_problems": problems}
