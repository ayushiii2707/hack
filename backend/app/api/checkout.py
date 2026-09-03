"""Checkout APIs.

/review  – validate cart, compute authoritative price, check upsell opportunity
/summary – read-only current review data
/confirm – confirm customer intent to pay, create the internal order
           (Razorpay order creation is layered in by PaymentService)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db
from app.schemas.checkout import CheckoutReviewOut, ConfirmCheckoutOut, OrderOut
from app.services.checkout_service import CheckoutService

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.post("/{session_id}/review", response_model=CheckoutReviewOut, summary="Open checkout review")
def review(session_id: str, db: Session = Depends(get_db)):
    return CheckoutReviewOut.from_review(CheckoutService(db).start_checkout(session_id))


@router.get("/{session_id}/summary", response_model=CheckoutReviewOut, summary="Current review data")
def summary(session_id: str, db: Session = Depends(get_db)):
    return CheckoutReviewOut.from_review(CheckoutService(db).get_summary(session_id))


@router.post(
    "/{session_id}/confirm",
    response_model=ConfirmCheckoutOut,
    summary="Confirm intent to pay and create the internal order (idempotent)",
)
def confirm(session_id: str, db: Session = Depends(get_db)):
    svc = CheckoutService(db)
    order = svc.confirm_checkout(session_id)
    payment_init = None
    if settings.razorpay_configured:
        from app.services.payment_service import PaymentService

        payment_init = PaymentService(db).ensure_payment_order(order)
    return ConfirmCheckoutOut(order=OrderOut.from_model(order), payment=payment_init)
