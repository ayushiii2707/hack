"""Payment APIs.

The amount is always derived from the internal Order. `verify` is the ONLY
path that can mark an order paid, and only after Razorpay signature checks.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PaymentVerificationError
from app.database.database import get_db
from app.schemas.payment import (
    CreatePaymentOrderIn,
    PaymentAttemptOut,
    PaymentFailedIn,
    PaymentInitOut,
    PaymentLinkIn,
    PaymentLinkOut,
    VerifyPaymentIn,
    VerifyResultOut,
)
from app.services.checkout_service import CheckoutService
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/order", response_model=PaymentInitOut, summary="Create the Razorpay order for an internal order")
def create_payment_order(body: CreatePaymentOrderIn, db: Session = Depends(get_db)):
    data = PaymentService(db).create_payment_order(body.order_id)
    return PaymentInitOut.from_init(data)


@router.post(
    "/verify",
    response_model=VerifyResultOut,
    summary="Verify a Razorpay payment signature (only way an order becomes PAID)",
)
def verify_payment(body: VerifyPaymentIn, db: Session = Depends(get_db)):
    svc = PaymentService(db)
    try:
        result = svc.verify_payment(
            order_id=body.order_id,
            razorpay_order_id=body.razorpay_order_id,
            razorpay_payment_id=body.razorpay_payment_id,
            razorpay_signature=body.razorpay_signature,
        )
    except PaymentVerificationError as exc:
        # Attempt already recorded as FAILED inside the service.
        return VerifyResultOut(
            success=False,
            order_status=(exc.details or {}).get("order_status", "PAYMENT_FAILED"),
            payment_status="FAILED",
            attempt_number=0,
            message=exc.message,
        )
    return VerifyResultOut(**result.__dict__)


@router.post("/failed", response_model=VerifyResultOut, summary="Record a gateway payment failure")
def payment_failed(body: PaymentFailedIn, db: Session = Depends(get_db)):
    result = PaymentService(db).mark_payment_failed(
        order_id=body.order_id,
        reason=body.reason,
        razorpay_payment_id=body.razorpay_payment_id,
        error_code=body.error_code,
    )
    return VerifyResultOut(**result.__dict__)


@router.post("/link", response_model=PaymentLinkOut, summary="Create a Razorpay Payment Link fallback")
def payment_link(body: PaymentLinkIn, db: Session = Depends(get_db)):
    customer = {
        "name": body.customer_name,
        "email": body.customer_email,
        "contact": body.customer_contact,
    }
    data = PaymentService(db).create_payment_link(body.order_id, customer=customer)
    return PaymentLinkOut(
        payment_link_id=data["payment_link_id"],
        short_url=data.get("short_url"),
        amount=data.get("amount", 0),
        currency=data.get("currency", "INR"),
        reused=data.get("reused", False),
    )


@router.get("/order/{order_id}/attempts", response_model=list[PaymentAttemptOut], summary="All attempts for an order")
def list_attempts(order_id: str, db: Session = Depends(get_db)):
    return [PaymentAttemptOut.from_model(p) for p in PaymentService(db).list_attempts(order_id)]


@router.get("/{payment_id}", response_model=PaymentAttemptOut, summary="Get one payment attempt")
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    return PaymentAttemptOut.from_model(PaymentService(db).get_payment(payment_id))


if settings.environment != "production":

    @router.post(
        "/order/{order_id}/simulate-failure",
        response_model=VerifyResultOut,
        tags=["demo"],
        summary="[non-prod] Deterministically record a failed payment attempt for the demo",
    )
    def simulate_failure(order_id: str, db: Session = Depends(get_db)):
        result = PaymentService(db).mark_payment_failed(
            order_id=order_id,
            reason="Simulated gateway failure (demo): card declined by issuer.",
            error_code="BAD_REQUEST_ERROR",
        )
        return VerifyResultOut(**result.__dict__)
