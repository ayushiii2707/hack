"""Payment APIs (session-scoped).

Every call operates on *my* single open order (derived from the authenticated
session). The amount always comes from that order. `verify` is the only path
that can mark an order PAID, and only after signature + gateway reconciliation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_session
from app.core.config import settings
from app.core.exceptions import ForbiddenError, PaymentVerificationError
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.payment import (
    PaymentAttemptOut,
    PaymentFailedIn,
    PaymentInitOut,
    PaymentLinkOut,
    VerifyPaymentIn,
    VerifyResultOut,
)
from app.services.checkout_service import CheckoutService
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def _open_order(db: Session, session: ShopSession):
    # Deliberately the LATEST order, not only an OPEN one: once an order is
    # settled (PAID/CANCELLED), the service methods below already give a
    # friendly, correct response (e.g. "already verified", "already paid",
    # "cancelled and cannot be paid") — resolving to the open order only would
    # mask all of that behind a generic 404 for any retry after the order
    # reaches a terminal state (double-submit, browser retry, etc).
    return CheckoutService(db).latest_order_for_session(session.id)


@router.post("/order", response_model=PaymentInitOut, summary="Create the Razorpay order for my open order")
def create_payment_order(
    session: ShopSession = Depends(require_session), db: Session = Depends(get_db)
):
    order = _open_order(db, session)
    return PaymentInitOut.from_init(PaymentService(db).ensure_payment_order(order))


@router.post(
    "/verify",
    response_model=VerifyResultOut,
    summary="Verify a Razorpay payment (the only path to PAID)",
)
def verify_payment(
    body: VerifyPaymentIn,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    order = _open_order(db, session)
    try:
        result = PaymentService(db).verify_payment(
            order=order,
            razorpay_order_id=body.razorpay_order_id,
            razorpay_payment_id=body.razorpay_payment_id,
            razorpay_signature=body.razorpay_signature,
        )
    except PaymentVerificationError as exc:
        return VerifyResultOut(
            success=False,
            order_status=(exc.details or {}).get("order_status", order.status.value),
            payment_status="FAILED",
            attempt_number=0,
            message=exc.message,
        )
    return VerifyResultOut(**result.__dict__)


@router.post("/failed", response_model=VerifyResultOut, summary="Advisory: my payment attempt failed at the gateway")
def payment_failed(
    body: PaymentFailedIn,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    order = _open_order(db, session)
    result = PaymentService(db).record_client_failure(
        order=order, reason=body.reason, razorpay_payment_id=body.razorpay_payment_id
    )
    return VerifyResultOut(**result.__dict__)


@router.post("/link", response_model=PaymentLinkOut, summary="Create a Razorpay Payment Link fallback for my order")
def payment_link(
    session: ShopSession = Depends(require_session), db: Session = Depends(get_db)
):
    order = _open_order(db, session)
    data = PaymentService(db).create_payment_link(order)
    return PaymentLinkOut(
        payment_link_id=data["payment_link_id"],
        short_url=data.get("short_url"),
        amount=data.get("amount", 0),
        currency=data.get("currency", "INR"),
        reused=data.get("reused", False),
    )


@router.get("/attempts", response_model=list[PaymentAttemptOut], summary="Attempts for my most recent order")
def list_attempts(
    session: ShopSession = Depends(require_session), db: Session = Depends(get_db)
):
    order = CheckoutService(db).latest_order_for_session(session.id)
    return [PaymentAttemptOut.from_model(p) for p in PaymentService(db).list_attempts(order.id)]


if True:  # registered always; body guards on the flag so tests can toggle it

    @router.post(
        "/simulate-failure",
        response_model=VerifyResultOut,
        tags=["demo"],
        summary="[demo only] deterministically record a failed attempt for my open order",
    )
    def simulate_failure(
        session: ShopSession = Depends(require_session), db: Session = Depends(get_db)
    ):
        if not settings.enable_demo_endpoints:
            raise ForbiddenError("Demo endpoints are disabled (set ENABLE_DEMO_ENDPOINTS=true).")
        order = _open_order(db, session)
        from app.core.constants import AuditActor

        result = PaymentService(db).mark_payment_failed(
            order_id=order.id,
            reason="Simulated gateway failure (demo): card declined by issuer.",
            error_code="BAD_REQUEST_ERROR",
            actor=AuditActor.SYSTEM,
        )
        return VerifyResultOut(**result.__dict__)
