"""Razorpay webhook receiver.

Kept separate from frontend verification. Authenticity is checked with the
webhook secret; processing is idempotent so repeated deliveries are safe.
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


@router.post("/razorpay", summary="Razorpay webhook (idempotent)")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str = Header(default=""),
):
    raw = await request.body()
    body_str = raw.decode("utf-8")

    if settings.razorpay_webhook_secret:
        try:
            get_razorpay_client().verify_webhook_signature(
                body=body_str, signature=x_razorpay_signature
            )
        except PaymentVerificationError:
            log.warning("rejected webhook with bad signature")
            return {"status": "invalid_signature"}
    else:
        log.warning("RAZORPAY_WEBHOOK_SECRET not set – skipping signature check (dev only)")

    try:
        event = json.loads(body_str)
    except json.JSONDecodeError:
        return {"status": "bad_json"}

    result = PaymentService(db).handle_webhook_event(event)
    log.info("webhook %s -> %s", event.get("event"), result)
    return {"status": "ok", **result}
