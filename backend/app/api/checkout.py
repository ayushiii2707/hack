"""Checkout APIs (session-scoped).

/review  – validate my cart, compute the authoritative price, check the upsell
/summary – read-only current review data
/confirm – confirm intent to pay: create the internal order, reserve stock,
           lock the cart (idempotent)
/cancel  – cancel the open order, release stock, unlock the cart
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_session
from app.core.config import settings
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.checkout import CheckoutReviewOut, ConfirmCheckoutOut, OrderOut
from app.services.checkout_service import CheckoutService

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.post("/review", response_model=CheckoutReviewOut, summary="Open checkout review")
def review(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return CheckoutReviewOut.from_review(CheckoutService(db).start_checkout(session.id))


@router.get("/summary", response_model=CheckoutReviewOut, summary="Current review data")
def summary(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return CheckoutReviewOut.from_review(CheckoutService(db).get_summary(session.id))


@router.post(
    "/confirm",
    response_model=ConfirmCheckoutOut,
    summary="Confirm intent to pay: create the order + reserve stock (idempotent)",
)
def confirm(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    svc = CheckoutService(db)
    order = svc.confirm_checkout(session.id)
    payment_init = None
    if settings.razorpay_configured:
        from app.services.payment_service import PaymentService

        payment_init = PaymentService(db).ensure_payment_order(order)
    return ConfirmCheckoutOut(order=OrderOut.from_model(order), payment=payment_init)


@router.post("/cancel", status_code=204, summary="Cancel the open order and unlock the cart")
def cancel(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    CheckoutService(db).cancel_checkout(session.id)
    return None
