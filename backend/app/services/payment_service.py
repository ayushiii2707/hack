"""Payment orchestration.

Boundaries enforced here:
  * amount always comes from the internal Order (never frontend / LLM)
  * a payment is "successful" only after Razorpay signature verification
  * every attempt is a new row; failed attempts are preserved
  * verify / webhook / link creation are idempotent
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    AuditAction,
    AuditActor,
    OrderStatus,
    PaymentStatus,
    SessionState,
)
from app.core.exceptions import (
    OrderNotFoundError,
    PaymentError,
    PaymentVerificationError,
    RazorpayError,
)
from app.integrations.razorpay.client import RazorpayClient, get_razorpay_client
from app.integrations.razorpay.orders import create_order as rzp_create_order
from app.integrations.razorpay.payment_links import create_payment_link as rzp_create_link
from app.integrations.razorpay.payments import verify_checkout_signature
from app.models.order import Order
from app.models.payment import Payment
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService
from app.utils.logging import get_logger

log = get_logger("payment")


@dataclass
class VerifyResult:
    success: bool
    order_status: str
    payment_status: str
    attempt_number: int
    message: str


class PaymentService:
    def __init__(self, db: Session, *, client: RazorpayClient | None = None):
        self.db = db
        self.orders = OrderRepository(db)
        self.payments = PaymentRepository(db)
        self.sessions = SessionRepository(db)
        self.audit = AuditService(db)
        self._client = client
        self._client_explicit = client is not None

    @property
    def client(self) -> RazorpayClient:
        if self._client is None:
            self._client = get_razorpay_client()
        return self._client

    # ---- order creation ----
    def _get_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} was not found.")
        return order

    def ensure_payment_order(self, order: Order) -> dict:
        """Create the Razorpay order once; return frontend init data (no secrets)."""
        if not settings.razorpay_configured and not self._client_explicit:
            raise RazorpayError("Razorpay is not configured on the server.")

        if not order.razorpay_order_id:
            created = rzp_create_order(
                self.client,
                amount_paise=order.amount,
                currency=order.currency,
                receipt=order.receipt or order.id,
                notes={"internal_order_id": order.id, "session_id": order.session_id},
            )
            self.orders.set_razorpay_order_id(order, created["razorpay_order_id"])
            if order.status == OrderStatus.CREATED:
                self.orders.set_status(order, OrderStatus.PAYMENT_PENDING)
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_ATTEMPTED,
                reason=f"Razorpay order {created['razorpay_order_id']} created for {order.amount} paise.",
                order_id=order.id,
                session_id=order.session_id,
                metadata={
                    "razorpay_order_id": created["razorpay_order_id"],
                    "amount": order.amount,
                    "currency": order.currency,
                },
            )
            self.db.commit()
            self.db.refresh(order)

        return self.payment_init_data(order)

    def payment_init_data(self, order: Order) -> dict:
        return {
            "key_id": settings.razorpay_key_id,
            "razorpay_order_id": order.razorpay_order_id,
            "order_id": order.id,
            "amount": order.amount,
            "currency": order.currency,
            "name": settings.app_name,
            "description": f"Order {order.id}",
            "notes": {"internal_order_id": order.id},
        }

    def create_payment_order(self, order_id: str) -> dict:
        return self.ensure_payment_order(self._get_order(order_id))

    # ---- attempts ----
    def record_payment_attempt(self, order_id: str, *, method: str = "checkout") -> Payment:
        payment = self.payments.create_attempt(order_id=order_id, method=method)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_ATTEMPTED,
            reason=f"Payment attempt #{payment.attempt_number} started ({method}).",
            order_id=order_id,
            metadata={"attempt_number": payment.attempt_number, "method": method},
        )
        self.db.commit()
        return payment

    # ---- verification (success path) ----
    def verify_payment(
        self,
        *,
        order_id: str,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> VerifyResult:
        order = self._get_order(order_id)

        if order.razorpay_order_id and order.razorpay_order_id != razorpay_order_id:
            raise PaymentVerificationError("Razorpay order id does not match this order.")

        # Idempotency: this payment already captured.
        existing = self.payments.get_by_razorpay_payment_id(razorpay_payment_id)
        if existing and existing.status == PaymentStatus.CAPTURED:
            return VerifyResult(
                True, order.status.value, existing.status.value, existing.attempt_number,
                "Payment already verified.",
            )
        if order.status == OrderStatus.PAID:
            latest = self.payments.latest_for_order(order_id)
            return VerifyResult(
                True, order.status.value, latest.status.value if latest else "CAPTURED",
                latest.attempt_number if latest else 1, "Order already paid.",
            )

        try:
            verify_checkout_signature(
                self.client,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
            )
        except PaymentVerificationError:
            result = self._fail(
                order,
                reason="Signature verification failed – payment NOT marked as paid.",
                razorpay_payment_id=razorpay_payment_id,
                actor=AuditActor.SYSTEM,
            )
            raise PaymentVerificationError(
                "Payment could not be verified.",
                details={"order_status": result.order_status},
            )

        payment = self.payments.create_attempt(order_id=order_id, status=PaymentStatus.CAPTURED)
        self.payments.update(
            payment,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            status=PaymentStatus.CAPTURED,
        )
        self.orders.set_status(order, OrderStatus.PAID)
        self._advance_session(order, SessionState.COMPLETED)
        self._complete_cart(order)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_SUCCESS,
            reason=f"Payment {razorpay_payment_id} verified and captured (attempt #{payment.attempt_number}).",
            order_id=order.id,
            session_id=order.session_id,
            actor=AuditActor.PAYMENT_PROVIDER,
            metadata={
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_order_id": razorpay_order_id,
                "attempt_number": payment.attempt_number,
                "amount": order.amount,
            },
        )
        self.db.commit()
        return VerifyResult(
            True, OrderStatus.PAID.value, PaymentStatus.CAPTURED.value,
            payment.attempt_number, "Payment verified.",
        )

    # ---- failure path ----
    def mark_payment_failed(
        self,
        *,
        order_id: str,
        reason: str,
        razorpay_payment_id: str | None = None,
        error_code: str | None = None,
    ) -> VerifyResult:
        order = self._get_order(order_id)
        if order.status == OrderStatus.PAID:
            raise PaymentError("Order is already paid; cannot mark it failed.")
        return self._fail(
            order, reason=reason, razorpay_payment_id=razorpay_payment_id,
            error_code=error_code, actor=AuditActor.PAYMENT_PROVIDER,
        )

    def _fail(
        self,
        order: Order,
        *,
        reason: str,
        razorpay_payment_id: str | None,
        error_code: str | None = None,
        actor: AuditActor = AuditActor.SYSTEM,
    ) -> VerifyResult:
        payment = self.payments.create_attempt(order_id=order.id, status=PaymentStatus.FAILED)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_ATTEMPTED,
            reason=f"Payment attempt #{payment.attempt_number} submitted to the gateway.",
            order_id=order.id,
            session_id=order.session_id,
            actor=AuditActor.SYSTEM,
            metadata={"attempt_number": payment.attempt_number},
        )
        self.payments.update(
            payment,
            status=PaymentStatus.FAILED,
            failure_reason=reason,
            razorpay_payment_id=razorpay_payment_id,
        )
        self.orders.set_status(order, OrderStatus.PAYMENT_FAILED)
        self._advance_session(order, SessionState.PAYMENT_FAILED)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_FAILED,
            reason=reason,
            order_id=order.id,
            session_id=order.session_id,
            actor=actor,
            metadata={
                "attempt_number": payment.attempt_number,
                "razorpay_payment_id": razorpay_payment_id,
                "error_code": error_code,
            },
        )
        self.db.commit()
        return VerifyResult(
            False, OrderStatus.PAYMENT_FAILED.value, PaymentStatus.FAILED.value,
            payment.attempt_number, reason,
        )

    # ---- payment link fallback ----
    def create_payment_link(self, order_id: str, *, customer: dict | None = None) -> dict:
        order = self._get_order(order_id)
        if order.status == OrderStatus.PAID:
            raise PaymentError("Order is already paid.")

        existing_link = next(
            (p for p in self.payments.list_for_order(order_id)
             if p.method == "payment_link" and p.razorpay_payment_link_id),
            None,
        )
        if existing_link:
            return {
                "payment_link_id": existing_link.razorpay_payment_link_id,
                "short_url": existing_link.payment_link_url,
                "amount": order.amount,
                "currency": order.currency,
                "reused": True,
            }

        link = rzp_create_link(
            self.client,
            amount_paise=order.amount,
            currency=order.currency,
            description=f"Checkout Copilot order {order.id}",
            reference_id=order.receipt or order.id,
            customer=customer,
            notes={"internal_order_id": order.id},
        )
        payment = self.payments.create_attempt(order_id=order_id, method="payment_link")
        self.payments.update(
            payment,
            method="payment_link",
            razorpay_payment_link_id=link["payment_link_id"],
            payment_link_url=link["short_url"],
            status=PaymentStatus.CREATED,
        )
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_LINK_CREATED,
            reason=f"Razorpay payment link created as fallback: {link['short_url']}",
            order_id=order.id,
            session_id=order.session_id,
            actor=AuditActor.SYSTEM,
            metadata={
                "payment_link_id": link["payment_link_id"],
                "short_url": link["short_url"],
                "amount": order.amount,
            },
        )
        self.db.commit()
        return {
            "payment_link_id": link["payment_link_id"],
            "short_url": link["short_url"],
            "amount": order.amount,
            "currency": order.currency,
            "reused": False,
        }

    # ---- webhook ----
    def handle_webhook_event(self, event: dict) -> dict:
        """Idempotent webhook processing. Returns a short status dict."""
        etype = event.get("event", "")
        payload = event.get("payload", {})
        entity = (payload.get("payment", {}) or {}).get("entity", {}) or {}
        razorpay_payment_id = entity.get("id")
        razorpay_order_id = entity.get("order_id")

        order = (
            self.orders.get_by_razorpay_id(razorpay_order_id) if razorpay_order_id else None
        )
        if order is None:
            return {"handled": False, "reason": "unknown order"}

        already = (
            self.payments.get_by_razorpay_payment_id(razorpay_payment_id)
            if razorpay_payment_id
            else None
        )

        if etype in ("payment.captured", "order.paid"):
            if order.status == OrderStatus.PAID or (already and already.status == PaymentStatus.CAPTURED):
                return {"handled": True, "idempotent": True, "order_status": order.status.value}
            payment = already or self.payments.create_attempt(
                order_id=order.id, status=PaymentStatus.CAPTURED
            )
            self.payments.update(
                payment, status=PaymentStatus.CAPTURED, razorpay_payment_id=razorpay_payment_id
            )
            self.orders.set_status(order, OrderStatus.PAID)
            self._advance_session(order, SessionState.COMPLETED)
            self._complete_cart(order)
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_SUCCESS,
                reason=f"Webhook {etype}: payment captured.",
                order_id=order.id,
                session_id=order.session_id,
                actor=AuditActor.PAYMENT_PROVIDER,
                metadata={"event": etype, "razorpay_payment_id": razorpay_payment_id},
            )
            self.db.commit()
            return {"handled": True, "order_status": OrderStatus.PAID.value}

        if etype == "payment.failed":
            if order.status == OrderStatus.PAID:
                return {"handled": True, "idempotent": True}
            if already and already.status == PaymentStatus.FAILED:
                return {"handled": True, "idempotent": True}
            self._fail(
                order,
                reason=f"Webhook payment.failed: {entity.get('error_description', 'payment failed')}",
                razorpay_payment_id=razorpay_payment_id,
                error_code=entity.get("error_code"),
                actor=AuditActor.PAYMENT_PROVIDER,
            )
            return {"handled": True, "order_status": OrderStatus.PAYMENT_FAILED.value}

        return {"handled": False, "reason": f"ignored event {etype}"}

    # ---- helpers ----
    def _advance_session(self, order: Order, target: SessionState) -> None:
        session = self.sessions.get(order.session_id)
        if session is None:
            return
        allowed = {
            SessionState.COMPLETED: {SessionState.PAYMENT_PENDING, SessionState.PAYMENT_FAILED},
            SessionState.PAYMENT_FAILED: {SessionState.PAYMENT_PENDING, SessionState.PAYMENT_FAILED},
        }
        if session.state in allowed.get(target, set()) or session.state == target:
            self.sessions.set_state(session, target)

    def _complete_cart(self, order: Order) -> None:
        from app.core.constants import CartStatus
        from app.repositories.cart_repository import CartRepository

        cart = CartRepository(self.db).get(order.cart_id)
        if cart is not None:
            cart.status = CartStatus.COMPLETED
            self.db.flush()

    def get_payment(self, payment_id: str) -> Payment:
        payment = self.payments.get(payment_id)
        if payment is None:
            raise OrderNotFoundError(f"Payment {payment_id} was not found.")
        return payment

    def list_attempts(self, order_id: str) -> list[Payment]:
        return self.payments.list_for_order(order_id)
