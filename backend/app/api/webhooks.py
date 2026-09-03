"""Razorpay webhook receiver.

Separate from browser-driven verification. Authenticity is mandatory: an
unsigned event is rejected (and, in a production environment, the app refuses
to start without ``RAZORPAY_WEBHOOK_SECRET``). Processing is idempotent — the
provider event id is a primary key in ``webhook_events``.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PaymentVerificationError
from app.database.database import get_db
from app.integrations.razorpay.client import get_razorpay_client
from app.services.payment_service import PaymentService
from app.utils.logging import get_logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger("webhook")


@router.post("/razorpay", summary="Razorpay webhook (signed, idempotent)")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
):
    raw = await request.body()
    body_str = raw.decode("utf-8", errors="replace")

    if not settings.razorpay_webhook_secret:
        # Fail closed. (In production the app won't even start in this state.)
        log.error("webhook rejected: RAZORPAY_WEBHOOK_SECRET is not configured")
        return _json(503, {"status": "webhook_not_configured"})

    try:
        get_razorpay_client().verify_webhook_signature(
            body=body_str, signature=x_razorpay_signature
        )
    except PaymentVerificationError:
        log.warning("webhook rejected: bad signature")
        return _json(400, {"status": "invalid_signature"})
    except Exception as exc:  # razorpay not constructible etc.
        log.error("webhook signature check errored: %s", exc)
        return _json(503, {"status": "verification_unavailable"})

    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        return _json(400, {"status": "bad_json"})

    result = PaymentService(db).handle_webhook_event(
        event, event_id=x_razorpay_event_id or event.get("id")
    )
    log.info("webhook %s -> %s", event.get("event"), result)
    return {"status": "ok", **result}


def _json(status: int, body: dict):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content=body)
