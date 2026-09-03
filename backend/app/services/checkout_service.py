"""Checkout orchestration.

"Confirm checkout" == the customer has confirmed intent to pay. It does NOT
mean payment succeeded – that only comes later from Razorpay verification.

Order amount is always computed server-side from the cart snapshot; the
frontend and the LLM never supply it.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.constants import (
    AuditAction,
    AuditActor,
    CartStatus,
    OrderStatus,
    SessionState,
)
from app.core.exceptions import CheckoutValidationError, OrderNotFoundError
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.pricing_service import PriceBreakdown, PricingService
from app.services.session_service import SessionService
from app.services.upsell_service import UpsellService
from app.utils.ids import receipt_id


@dataclass
class CheckoutReview:
    session_id: str
    cart_id: str
    breakdown: PriceBreakdown
    upsell_available: bool
    upsell_pending: bool
    issues: list[dict]


class CheckoutService:
    def __init__(self, db: Session):
        self.db = db
        self.sessions = SessionService(db)
        self.carts = CartService(db)
        self.pricing = PricingService(db)
        self.upsell = UpsellService(db)
        self.orders = OrderRepository(db)
        self.audit = AuditService(db)

    # ---- review ----
    def _upsell_pending(self, session) -> bool:
        return bool(session.upsell_shown and not session.upsell_accepted and not session.upsell_declined)

    def start_checkout(self, session_id: str) -> CheckoutReview:
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)
        issues = self.carts.validate_cart(cart.id, require_non_empty=True)
        breakdown = self.pricing.get_price_breakdown(cart.id)

        if session.state in (SessionState.CART_BUILDING, SessionState.BROWSING):
            self.sessions.transition_state(
                session, SessionState.CART_REVIEW, reason="Customer opened checkout review"
            )
        reco = self.upsell.peek(session_id)
        return CheckoutReview(
            session_id=session_id,
            cart_id=cart.id,
            breakdown=breakdown,
            upsell_available=reco is not None,
            upsell_pending=self._upsell_pending(session),
            issues=[i.__dict__ for i in issues],
        )

    def get_summary(self, session_id: str) -> CheckoutReview:
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)
        issues = self.carts.validate_cart(cart.id, require_non_empty=False)
        breakdown = self.pricing.get_price_breakdown(cart.id)
        reco = self.upsell.peek(session_id)
        return CheckoutReview(
            session_id=session_id,
            cart_id=cart.id,
            breakdown=breakdown,
            upsell_available=reco is not None,
            upsell_pending=self._upsell_pending(session),
            issues=[i.__dict__ for i in issues],
        )

    # ---- validate ----
    def validate_checkout(self, session_id: str) -> Order | None:
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)

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
        return self.orders.get_open_for_cart(cart.id)

    # ---- confirm ----
    def confirm_checkout(self, session_id: str, *, actor: AuditActor = AuditActor.CUSTOMER) -> Order:
        """Idempotent: returns the existing open order for this cart if present."""
        existing = self.validate_checkout(session_id)
        session = self.sessions.get_session(session_id)
        cart = self.carts.get_cart_for_session(session_id)
        breakdown = self.pricing.get_price_breakdown(cart.id)

        if existing is not None:
            # Keep the authoritative amount in sync if the cart changed meanwhile.
            if existing.status == OrderStatus.CREATED and existing.amount != breakdown.total:
                existing.amount = breakdown.total
                existing.subtotal = breakdown.subtotal
                existing.shipping = breakdown.shipping
                existing.tax = breakdown.tax
                self.db.commit()
            return existing

        if session.state in (SessionState.BROWSING, SessionState.CART_BUILDING, SessionState.UPSELL):
            self.sessions.transition_state(
                session, SessionState.CART_REVIEW, reason="Entering checkout confirmation"
            )

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
        self.carts.repo.set_status(cart, CartStatus.CHECKOUT)
        self.sessions.transition_state(
            session, SessionState.PAYMENT_PENDING, reason="Checkout confirmed by customer"
        )
        self.audit.log_event(
            actor=actor,
            action=AuditAction.CHECKOUT_STARTED,
            reason=f"Checkout confirmed. Authoritative amount {order.amount} paise.",
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

    def get_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} was not found.")
        return order

    def complete_order(self, order: Order) -> Order:
        self.orders.set_status(order, OrderStatus.PAID)
        cart = self.carts.repo.get(order.cart_id)
        if cart is not None:
            self.carts.repo.set_status(cart, CartStatus.COMPLETED)
        session = self.sessions.get_session(order.session_id)
        self.sessions.transition_state(
            session, SessionState.COMPLETED, reason="Payment captured"
        )
        self.db.commit()
        self.db.refresh(order)
        return order
