"""Payment orchestration.

Hard invariants (enforced here, not by the prompt or the frontend):
  * the amount always comes from the internal Order (paise), never a caller;
  * an order reaches PAID only after BOTH the Razorpay signature verifies AND a
    fresh gateway fetch confirms status + amount + currency + order id;
  * every attempt is its own row; a CAPTURED/FAILED row is never rewritten;
  * verify / webhook / payment-link creation are idempotent, with the
    idempotency backstop in the database (unique constraints, event table).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    AuditAction,
    AuditActor,
    CartStatus,
    OrderStatus,
    PaymentStatus,
    SessionState,
)
from app.core.exceptions import (
    ConflictError,
    OrderNotFoundError,
    PaymentError,
    PaymentVerificationError,
    RazorpayError,
)
from app.integrations.razorpay.client import RazorpayClient, get_razorpay_client
from app.integrations.razorpay.orders import create_order as rzp_create_order
from app.integrations.razorpay.payment_links import create_payment_link as rzp_create_link
from app.integrations.razorpay.payments import fetch_payment, verify_checkout_signature
from app.models.order import Order
from app.models.payment import Payment
from app.models.webhook_event import WebhookEvent
from app.repositories.cart_repository import CartRepository
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
        self.carts = CartRepository(db)
        self.audit = AuditService(db)
        self._client = client
        self._client_explicit = client is not None

    @property
    def client(self) -> RazorpayClient:
        if self._client is None:
            self._client = get_razorpay_client()
        return self._client

    # ---------------------------------------------------------------- helpers
    def _get_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} was not found.")
        return order

    def _advance_session(self, order: Order, target: SessionState) -> None:
        session = self.sessions.get(order.session_id)
        if session is None:
            return
        allowed = {
            SessionState.COMPLETED: {
                SessionState.PAYMENT_PENDING,
                SessionState.PAYMENT_FAILED,
            },
            SessionState.PAYMENT_FAILED: {
                SessionState.PAYMENT_PENDING,
                SessionState.PAYMENT_FAILED,
            },
        }
        if session.state == target or session.state in allowed.get(target, set()):
            self.sessions.set_state(session, target)

    def _complete_cart(self, order: Order) -> None:
        cart = CartRepository(self.db).get(order.cart_id)
        if cart is not None and cart.status != CartStatus.COMPLETED:
            cart.status = CartStatus.COMPLETED
            self.db.flush()

    def _mark_paid(self, order: Order, *, source: str, gateway_amount: int | None) -> None:
        self.orders.set_status(order, OrderStatus.PAID)  # also nulls open_cart_key
        self._advance_session(order, SessionState.COMPLETED)
        self._complete_cart(order)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_SUCCESS,
            reason=f"Payment verified via {source}; order marked PAID for {order.amount} paise.",
            order_id=order.id,
            session_id=order.session_id,
            actor=AuditActor.PAYMENT_PROVIDER,
            metadata={"source": source, "gateway_amount": gateway_amount, "amount": order.amount},
        )

    # ---------------------------------------------------------------- order
    def ensure_payment_order(self, order: Order) -> dict:
        """Create the Razorpay order once; return frontend init data (no secrets)."""
        if not settings.razorpay_configured and not self._client_explicit:
            raise RazorpayError("Razorpay is not configured on the server.")
        if order.status == OrderStatus.PAID:
            raise ConflictError("This order is already paid.")

        if not order.razorpay_order_id:
            receipt = order.receipt or order.id
            recovered = None
            try:
                recovered = self.client.find_order_by_receipt(receipt)
            except Exception:  # pragma: no cover - best effort recovery
                recovered = None

            if recovered and int(recovered.get("amount", -1)) == order.amount:
                rzp_order_id = recovered["id"]
            else:
                created = rzp_create_order(
                    self.client,
                    amount_paise=order.amount,
                    currency=order.currency,
                    receipt=receipt,
                    notes={"internal_order_id": order.id, "session_id": order.session_id},
                )
                rzp_order_id = created["razorpay_order_id"]

            self.orders.set_razorpay_order_id(order, rzp_order_id)
            if order.status == OrderStatus.CREATED:
                self.orders.set_status(order, OrderStatus.PAYMENT_PENDING)
            # Commit the id immediately so a crash here can't orphan a Razorpay order.
            self.db.commit()
            self.db.refresh(order)
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_ATTEMPTED,
                reason=f"Razorpay order {rzp_order_id} ready for {order.amount} paise.",
                order_id=order.id,
                session_id=order.session_id,
                metadata={"razorpay_order_id": rzp_order_id, "amount": order.amount},
            )
            self.db.commit()

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

    # ---------------------------------------------------------------- verify
    def verify_payment(
        self,
        *,
        order: Order,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> VerifyResult:
        if order.status == OrderStatus.CANCELLED:
            raise ConflictError("This order was cancelled and cannot be paid.")
        # Idempotency — already captured.
        cap = self.payments.get_captured(order.id)
        if cap is not None or order.status == OrderStatus.PAID:
            latest = cap or self.payments.latest_for_order(order.id)
            return VerifyResult(
                True, OrderStatus.PAID.value,
                (latest.status.value if latest else PaymentStatus.CAPTURED.value),
                (latest.attempt_number if latest else 1),
                "Payment already verified.",
            )

        if order.razorpay_order_id and order.razorpay_order_id != razorpay_order_id:
            # Forged / mismatched input — do NOT touch order state.
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_VERIFICATION_FAILED,
                reason="Razorpay order id does not match this order; verification rejected.",
                order_id=order.id, session_id=order.session_id, actor=AuditActor.SYSTEM,
                metadata={"provided_order_id": razorpay_order_id},
            )
            self.db.commit()
            raise PaymentVerificationError("Razorpay order id does not match this order.")

        # 1. Signature (local HMAC).
        try:
            verify_checkout_signature(
                self.client,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
            )
        except PaymentVerificationError:
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_VERIFICATION_FAILED,
                reason="Signature verification failed; order NOT marked paid.",
                order_id=order.id, session_id=order.session_id, actor=AuditActor.SYSTEM,
                metadata={"razorpay_payment_id": razorpay_payment_id},
            )
            self.db.commit()
            raise PaymentVerificationError("Payment could not be verified.")

        # 2. Independent reconciliation with the gateway.
        gp = fetch_payment(self.client, razorpay_payment_id)
        problems: list[str] = []
        if gp.order_id and order.razorpay_order_id and gp.order_id != order.razorpay_order_id:
            problems.append("gateway order id mismatch")
        if not gp.is_settled:
            problems.append(f"gateway status is '{gp.status}'")
        if gp.amount is not None and int(gp.amount) != order.amount:
            problems.append(f"amount mismatch (gateway {gp.amount} != order {order.amount})")
        if gp.currency and gp.currency != order.currency:
            problems.append("currency mismatch")
        if problems:
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_VERIFICATION_FAILED,
                reason="Gateway reconciliation failed: " + "; ".join(problems),
                order_id=order.id, session_id=order.session_id, actor=AuditActor.SYSTEM,
                metadata={"razorpay_payment_id": razorpay_payment_id, "problems": problems},
            )
            self.db.commit()
            raise PaymentVerificationError(
                "Payment could not be verified against the gateway."
            )

        # 3. Record the CAPTURED attempt (unique constraint on captured_payment_key
        #    is the final idempotency backstop under concurrency).
        payment = self.payments.create_attempt(order_id=order.id, status=PaymentStatus.ATTEMPTED)
        try:
            self.payments.finalize(
                payment,
                status=PaymentStatus.CAPTURED,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
                captured_payment_key=razorpay_payment_id,
                settled_amount=int(gp.amount) if gp.amount is not None else order.amount,
            )
            self._mark_paid(order, source="checkout-verify", gateway_amount=gp.amount)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            self.db.refresh(order)
            latest = self.payments.get_captured(order.id) or self.payments.latest_for_order(order.id)
            return VerifyResult(
                True, OrderStatus.PAID.value,
                latest.status.value if latest else PaymentStatus.CAPTURED.value,
                latest.attempt_number if latest else 1,
                "Payment already verified (concurrent).",
            )

        return VerifyResult(
            True, OrderStatus.PAID.value, PaymentStatus.CAPTURED.value,
            payment.attempt_number, "Payment verified.",
        )

    # ---------------------------------------------------------------- failure
    def record_client_failure(
        self, *, order: Order, reason: str, razorpay_payment_id: str | None = None
    ) -> VerifyResult:
        """Advisory failure reported by the browser (modal dismissed, card declined).

        Never contradicts an authoritative capture.
        """
        if order.status == OrderStatus.PAID or self.payments.get_captured(order.id):
            raise ConflictError("This order is already paid.")
        try:
            return self._fail(
                order,
                reason=f"Client-reported failure: {reason}"[:500],
                razorpay_payment_id=razorpay_payment_id,
                actor=AuditActor.CUSTOMER,
            )
        except IntegrityError:
            # Concurrent duplicate report — the order is already marked failed.
            self.db.rollback()
            self.db.refresh(order)
            latest = self.payments.latest_for_order(order.id)
            return VerifyResult(
                False, order.status.value,
                latest.status.value if latest else PaymentStatus.FAILED.value,
                latest.attempt_number if latest else 1,
                "Payment failure already recorded.",
            )

    def mark_payment_failed(
        self,
        *,
        order_id: str,
        reason: str,
        razorpay_payment_id: str | None = None,
        error_code: str | None = None,
        actor: AuditActor = AuditActor.PAYMENT_PROVIDER,
    ) -> VerifyResult:
        order = self._get_order(order_id)
        if order.status == OrderStatus.PAID:
            raise PaymentError("Order is already paid; cannot mark it failed.")
        return self._fail(
            order, reason=reason, razorpay_payment_id=razorpay_payment_id,
            error_code=error_code, actor=actor,
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
        payment = self.payments.create_attempt(order_id=order.id, status=PaymentStatus.ATTEMPTED)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_ATTEMPTED,
            reason=f"Payment attempt #{payment.attempt_number} submitted to the gateway.",
            order_id=order.id, session_id=order.session_id, actor=AuditActor.SYSTEM,
            metadata={"attempt_number": payment.attempt_number},
        )
        self.payments.finalize(
            payment,
            status=PaymentStatus.FAILED,
            failure_reason=reason,
            razorpay_payment_id=razorpay_payment_id,
        )
        if order.status != OrderStatus.PAID:
            self.orders.set_status(order, OrderStatus.PAYMENT_FAILED)
            self._advance_session(order, SessionState.PAYMENT_FAILED)
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_FAILED,
            reason=reason,
            order_id=order.id, session_id=order.session_id, actor=actor,
            metadata={"attempt_number": payment.attempt_number, "error_code": error_code},
        )
        self.db.commit()
        return VerifyResult(
            False, OrderStatus.PAYMENT_FAILED.value, PaymentStatus.FAILED.value,
            payment.attempt_number, reason,
        )

    # ---------------------------------------------------------------- link
    def create_payment_link(self, order: Order) -> dict:
        if order.status == OrderStatus.PAID:
            raise ConflictError("This order is already paid.")

        existing = next(
            (p for p in self.payments.list_for_order(order.id)
             if p.method == "payment_link" and p.razorpay_payment_link_id),
            None,
        )
        if existing is not None:
            return {
                "payment_link_id": existing.razorpay_payment_link_id,
                "short_url": existing.payment_link_url,
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
            customer=None,  # never send arbitrary customer contact from a request
            notes={"internal_order_id": order.id},
        )
        payment = self.payments.create_attempt(order_id=order.id, method="payment_link",
                                               status=PaymentStatus.CREATED)
        payment.method = "payment_link"
        payment.razorpay_payment_link_id = link["payment_link_id"]
        payment.payment_link_url = link["short_url"]
        self.db.flush()
        self.audit.log_payment_event(
            action=AuditAction.PAYMENT_LINK_CREATED,
            reason=f"Razorpay payment link {link['payment_link_id']} created as fallback.",
            order_id=order.id, session_id=order.session_id, actor=AuditActor.SYSTEM,
            metadata={"payment_link_id": link["payment_link_id"], "amount": order.amount},
        )
        self.db.commit()
        return {
            "payment_link_id": link["payment_link_id"],
            "short_url": link["short_url"],
            "amount": order.amount,
            "currency": order.currency,
            "reused": False,
        }

    # ---------------------------------------------------------------- webhook
    def _dedupe_event(self, event_id: str | None, event_type: str) -> bool:
        """Return True if this event id was already processed (DB-enforced)."""
        if not event_id:
            return False
        try:
            self.db.add(WebhookEvent(id=event_id, event_type=event_type))
            self.db.flush()
            return False
        except IntegrityError:
            self.db.rollback()
            return True

    def handle_webhook_event(self, event: dict, *, event_id: str | None = None) -> dict:
        etype = event.get("event", "")
        if self._dedupe_event(event_id, etype):
            return {"handled": True, "idempotent": True}

        payload = event.get("payload", {}) or {}
        pay_entity = (payload.get("payment", {}) or {}).get("entity", {}) or {}
        order_entity = (payload.get("order", {}) or {}).get("entity", {}) or {}

        razorpay_payment_id = pay_entity.get("id")
        razorpay_order_id = pay_entity.get("order_id") or order_entity.get("id")
        entity_amount = pay_entity.get("amount")
        if entity_amount is None:
            entity_amount = order_entity.get("amount")

        order = (
            self.orders.get_by_razorpay_id(razorpay_order_id) if razorpay_order_id else None
        )
        if order is None:
            self.db.commit()  # keep the dedupe row
            return {"handled": False, "reason": "unknown order"}

        if order.status == OrderStatus.CANCELLED:
            # Money moved against an order the customer cancelled -> needs a human
            # (refund). Never auto-resurrect it.
            self.audit.log_payment_event(
                action=AuditAction.PAYMENT_VERIFICATION_FAILED,
                reason=f"Webhook {etype} for a CANCELLED order; manual reconciliation required.",
                order_id=order.id, session_id=order.session_id,
                actor=AuditActor.PAYMENT_PROVIDER, metadata={"event": etype},
            )
            self.db.commit()
            return {"handled": True, "needs_reconciliation": True}

        if etype in ("payment.captured", "order.paid"):
            if order.status == OrderStatus.PAID or self.payments.get_captured(order.id):
                self.db.commit()
                return {"handled": True, "idempotent": True, "order_status": order.status.value}

            problems: list[str] = []
            if entity_amount is not None and int(entity_amount) != order.amount:
                problems.append(f"amount mismatch ({entity_amount} != {order.amount})")
            # Best-effort independent confirmation.
            if razorpay_payment_id and (self._client is not None or settings.razorpay_configured):
                try:
                    gp = fetch_payment(self.client, razorpay_payment_id)
                    if not gp.is_settled:
                        problems.append(f"gateway status '{gp.status}'")
                    if gp.amount is not None and int(gp.amount) != order.amount:
                        problems.append("gateway amount mismatch")
                except RazorpayError:  # pragma: no cover - network best effort
                    pass
            if problems:
                self.audit.log_payment_event(
                    action=AuditAction.PAYMENT_VERIFICATION_FAILED,
                    reason="Webhook reconciliation failed: " + "; ".join(problems),
                    order_id=order.id, session_id=order.session_id,
                    actor=AuditActor.PAYMENT_PROVIDER,
                    metadata={"event": etype, "problems": problems},
                )
                self.db.commit()
                return {"handled": True, "rejected": True, "reason": "reconciliation failed"}

            payment = self.payments.create_attempt(order_id=order.id, status=PaymentStatus.ATTEMPTED)
            try:
                self.payments.finalize(
                    payment,
                    status=PaymentStatus.CAPTURED,
                    razorpay_payment_id=razorpay_payment_id,
                    captured_payment_key=razorpay_payment_id or f"wh-{order.id}",
                    settled_amount=int(entity_amount) if entity_amount is not None else order.amount,
                )
                self._mark_paid(order, source=f"webhook:{etype}", gateway_amount=entity_amount)
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                return {"handled": True, "idempotent": True}
            return {"handled": True, "order_status": OrderStatus.PAID.value}

        if etype == "payment.failed":
            if order.status == OrderStatus.PAID or self.payments.get_captured(order.id):
                self.db.commit()
                return {"handled": True, "idempotent": True}
            existing_failed = self.payments.get_by_razorpay_payment_id(razorpay_payment_id) if razorpay_payment_id else None
            if existing_failed and existing_failed.status == PaymentStatus.FAILED:
                self.db.commit()
                return {"handled": True, "idempotent": True}
            self._fail(
                order,
                reason=f"Webhook payment.failed: {pay_entity.get('error_description', 'payment failed')}",
                razorpay_payment_id=razorpay_payment_id,
                error_code=pay_entity.get("error_code"),
                actor=AuditActor.PAYMENT_PROVIDER,
            )
            return {"handled": True, "order_status": OrderStatus.PAYMENT_FAILED.value}

        self.db.commit()
        return {"handled": False, "reason": f"ignored event {etype}"}

    # ---------------------------------------------------------------- reads
    def get_payment(self, payment_id: str) -> Payment:
        payment = self.payments.get(payment_id)
        if payment is None:
            raise OrderNotFoundError(f"Payment {payment_id} was not found.")
        return payment

    def list_attempts(self, order_id: str) -> list[Payment]:
        return self.payments.list_for_order(order_id)
