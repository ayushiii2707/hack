"""Checkout orchestration.

"Confirm checkout" == the customer has confirmed intent to pay. It does NOT
mean payment succeeded – that only comes later from Razorpay verification.

At confirm:
  * order amount is computed server-side from the cart snapshot;
  * stock for every line is atomically reserved (guarded UPDATE);
  * the cart is locked (status CHECKOUT) so it can no longer diverge from the order;
  * "one open order per cart" is enforced by a UNIQUE column, not a Python check.
Cancelling a checkout releases the stock and unlocks the cart.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import (
    AuditAction,
    AuditActor,
    CartStatus,
    OrderStatus,
    SessionState,
)
from app.core.exceptions import CheckoutValidationError, ConflictError, OrderNotFoundError
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.pricing_service import PriceBreakdown, PricingService
from app.services.session_service import SessionService
from app.services.upsell_service import UpsellService
from app.utils.ids import receipt_id
from app.utils.logging import get_logger

log = get_logger("checkout")


@dataclass
class CheckoutReview:
    session_id: str
    cart_id: str
    breakdown: PriceBreakdown
    upsell_available: bool
    upsell_pending: bool
    issues: list[dict]
    has_open_order: bool = False


class CheckoutService:
    def __init__(self, db: Session):
        self.db = db
        self.sessions = SessionService(db)
        self.carts = CartService(db)
        self.pricing = PricingService(db)
        self.upsell = UpsellService(db)
        self.orders = OrderRepository(db)
        self.products = ProductRepository(db)
        self.audit = AuditService(db)

    # ---- review ----
    def _upsell_pending(self, session) -> bool:
        return bool(
            session.upsell_shown and not session.upsell_accepted and not session.upsell_declined
        )

    def _review(self, session_id: str, *, require_non_empty: bool) -> CheckoutReview:
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)
        issues = self.carts.validate_cart(cart.id, require_non_empty=require_non_empty)
        breakdown = self.pricing.get_price_breakdown(cart.id)
        reco = self.upsell.peek(session_id)
        return CheckoutReview(
            session_id=session_id,
            cart_id=cart.id,
            breakdown=breakdown,
            upsell_available=reco is not None,
            upsell_pending=self._upsell_pending(session),
            issues=[i.__dict__ for i in issues],
            has_open_order=self.orders.get_open_for_session(session_id) is not None,
        )

    def start_checkout(self, session_id: str) -> CheckoutReview:
        session = self.sessions.get_session(session_id)
        review = self._review(session_id, require_non_empty=True)
        if session.state in (SessionState.CART_BUILDING, SessionState.BROWSING):
            self.sessions.transition_state(
                session, SessionState.CART_REVIEW, reason="Customer opened checkout review"
            )
        return review

    def get_summary(self, session_id: str) -> CheckoutReview:
        return self._review(session_id, require_non_empty=False)

    # ---- validate ----
    def validate_checkout(self, session_id: str) -> Order | None:
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)

        existing = self.orders.get_open_for_session(session_id)
        if existing is not None:
            return existing

        if not cart.items:
            raise CheckoutValidationError("Your cart is empty.")
        issues = self.carts.validate_cart(cart.id, require_non_empty=True)
        if issues:
            raise CheckoutValidationError(
                "Some items are no longer purchasable.",
                details={"issues": [i.__dict__ for i in issues]},
            )
        if self._upsell_pending(session):
            raise CheckoutValidationError(
                "Please accept or decline the suggested add-on before checking out."
            )
        return None

    # ---- confirm ----
    def confirm_checkout(self, session_id: str, *, actor: AuditActor = AuditActor.CUSTOMER) -> Order:
        """Idempotent: returns the existing open order for this session if present."""
        existing = self.validate_checkout(session_id)
        if existing is not None:
            return existing

        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)
        breakdown = self.pricing.get_price_breakdown(cart.id)

        if session.state in (
            SessionState.BROWSING,
            SessionState.CART_BUILDING,
            SessionState.UPSELL,
        ):
            self.sessions.transition_state(
                session, SessionState.CART_REVIEW, reason="Entering checkout confirmation"
            )

        try:
            order = self.orders.create(
                session_id=session_id,
                cart_id=cart.id,
                amount=breakdown.total,
                subtotal=breakdown.subtotal,
                shipping=breakdown.shipping,
                tax=breakdown.tax,
                currency=breakdown.currency,
                receipt=receipt_id(),
            )
            self.db.flush()
        except IntegrityError:
            # Lost the race for the single open-order slot -> return the winner.
            self.db.rollback()
            winner = self.orders.get_open_for_session(session_id)
            if winner is not None:
                return winner
            raise

        # Atomically reserve stock for every line. All-or-nothing.
        reserved: list[tuple[str, int]] = []
        for item in cart.items:
            if self.products.try_decrement_stock(item.product_id, item.quantity):
                reserved.append((item.product_id, item.quantity))
            else:
                for pid, q in reserved:
                    self.products.increment_stock(pid, q)
                self.db.rollback()
                name = item.product.name if item.product else item.product_id
                raise CheckoutValidationError(
                    f"'{name}' is no longer available in the requested quantity.",
                    details={"product_id": item.product_id, "requested": item.quantity},
                )
        order.stock_reserved = True

        self.carts.repo.set_status(cart, CartStatus.CHECKOUT)
        self.sessions.transition_state(
            session, SessionState.PAYMENT_PENDING, reason="Checkout confirmed by customer"
        )
        self.audit.log_event(
            actor=AuditActor.SYSTEM,
            action=AuditAction.STOCK_RESERVED,
            reason=f"Reserved stock for {len(reserved)} line(s) on order {order.id}.",
            session_id=session_id,
            order_id=order.id,
            metadata={"lines": [{"product_id": p, "quantity": q} for p, q in reserved]},
        )
        self.audit.log_event(
            actor=actor,
            action=AuditAction.CHECKOUT_STARTED,
            reason=f"Checkout confirmed. Authoritative amount {order.amount} paise. Stock reserved.",
            session_id=session_id,
            order_id=order.id,
            metadata={
                "amount": order.amount,
                "subtotal": order.subtotal,
                "shipping": order.shipping,
                "item_count": len(cart.items),
            },
        )
        self.db.commit()
        self.db.refresh(order)
        return order

    # ---- cancel ----
    def cancel_checkout(self, session_id: str, *, reason: str = "Customer cancelled checkout") -> None:
        order = self.orders.get_open_for_session(session_id)
        if order is None:
            # Nothing to cancel; make sure the cart is usable again.
            cart = self.carts.get_cart_for_session(session_id)
            if cart.status != CartStatus.ACTIVE:
                self.carts.repo.set_status(cart, CartStatus.ACTIVE)
                self.db.commit()
            return
        from app.repositories.payment_repository import PaymentRepository

        if order.status == OrderStatus.PAID or PaymentRepository(self.db).has_captured(order.id):
            raise ConflictError("This order has been paid and cannot be cancelled here.")

        # Atomically claim the open->CANCELLED transition. If we lose the race to
        # a concurrent capture, back off and do NOT release the (now sold) stock.
        if not self.orders.try_close_open_order(order.id, OrderStatus.CANCELLED):
            self.db.rollback()
            raise ConflictError("This order was just paid and can no longer be cancelled.")
        self.db.refresh(order)  # ORM object now reflects the CANCELLED status

        if order.stock_reserved:
            released: list[dict] = []
            cart = self.carts.repo.get(order.cart_id)
            if cart is not None:
                for item in cart.items:
                    self.products.increment_stock(item.product_id, item.quantity)
                    released.append({"product_id": item.product_id, "quantity": item.quantity})
            order.stock_reserved = False
            self.audit.log_event(
                actor=AuditActor.SYSTEM,
                action=AuditAction.STOCK_RELEASED,
                reason=f"Released reserved stock for {len(released)} line(s) on cancelled order {order.id}.",
                session_id=session_id,
                order_id=order.id,
                metadata={"lines": released},
            )

        cart = self.carts.repo.get(order.cart_id)
        if cart is not None:
            self.carts.repo.set_status(cart, CartStatus.ACTIVE)
        session = self.sessions.get_session(session_id)
        if session.state in (SessionState.PAYMENT_PENDING, SessionState.PAYMENT_FAILED):
            self.sessions.transition_state(
                session, SessionState.CART_BUILDING, reason="Checkout cancelled"
            )
        self.audit.log_event(
            actor=AuditActor.CUSTOMER,
            action=AuditAction.CHECKOUT_CANCELLED,
            reason=f"Checkout cancelled; stock released. {reason}",
            session_id=session_id,
            order_id=order.id,
            metadata={"cancelled_order": order.id},
        )
        self.db.commit()

    def get_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} was not found.")
        return order

    def open_order_for_session(self, session_id: str) -> Order:
        order = self.orders.get_open_for_session(session_id)
        if order is None:
            raise OrderNotFoundError("No open order for this session. Confirm checkout first.")
        return order

    def latest_order_for_session(self, session_id: str) -> Order:
        order = self.orders.latest_for_session(session_id)
        if order is None:
            raise OrderNotFoundError("This session has no order yet.")
        return order
