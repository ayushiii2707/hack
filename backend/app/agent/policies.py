"""Agent policy engine – the second line of defence.

Even though the services enforce their own hard limits, every agent tool call
passes through here first. A denied policy is audited as POLICY_BLOCKED and the
tool returns a structured error the LLM can explain (it cannot bypass it).

Prompt-level restrictions are NOT security. This is.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import SessionState
from app.repositories.cart_repository import CartRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.allowed


ALLOW = PolicyDecision(True)


class PolicyEngine:
    def __init__(self, db: Session, session_id: str):
        self.db = db
        self.session_id = session_id
        self.sessions = SessionRepository(db)
        self.carts = CartRepository(db)
        self.orders = OrderRepository(db)
        self.audit = AuditService(db)

    def _deny(self, reason: str, **meta) -> PolicyDecision:
        self.audit.log_policy_block(
            reason=reason, session_id=self.session_id, metadata=meta or None
        )
        self.db.commit()
        return PolicyDecision(False, reason)

    # ---- individual policies ----
    def can_search_products(self) -> PolicyDecision:
        return ALLOW

    def can_get_product(self) -> PolicyDecision:
        return ALLOW

    def can_modify_cart(self, *, quantity: int | None = None) -> PolicyDecision:
        session = self.sessions.get(self.session_id)
        if session is None:
            return self._deny("Unknown session.")
        if session.state in (SessionState.PAYMENT_PENDING, SessionState.COMPLETED):
            return self._deny(
                f"Cart is locked while the session is {session.state.value}.",
                state=session.state.value,
            )
        if quantity is not None and quantity > settings.max_item_quantity:
            return self._deny(
                f"Requested quantity {quantity} exceeds the maximum of "
                f"{settings.max_item_quantity}.",
                requested_quantity=quantity,
                max_quantity=settings.max_item_quantity,
            )
        if quantity is not None and quantity < 1:
            return self._deny(f"Invalid quantity {quantity}.", requested_quantity=quantity)
        return ALLOW

    def can_show_upsell(self) -> PolicyDecision:
        session = self.sessions.get(self.session_id)
        if session is None:
            return self._deny("Unknown session.")
        if session.upsell_shown:
            return self._deny(
                "An upsell was already shown in this session; only one is allowed.",
                upsell_shown=True,
                upsell_declined=session.upsell_declined,
                upsell_accepted=session.upsell_accepted,
            )
        cart = self.carts.get_by_session(self.session_id)
        if cart is None or not cart.items:
            return self._deny("Cannot show an upsell for an empty cart.")
        return ALLOW

    def can_start_checkout(self) -> PolicyDecision:
        cart = self.carts.get_by_session(self.session_id)
        if cart is None or not cart.items:
            return self._deny("Cannot start checkout with an empty cart.")
        return ALLOW

    def can_create_payment(self) -> PolicyDecision:
        # The agent may never trigger payment execution – only surface the
        # checkout so the customer clicks Pay themselves.
        return self._deny("The agent cannot execute payments; the customer must confirm and pay.")

    def can_retry_payment(self) -> PolicyDecision:
        return self._deny("The agent cannot execute payments; the customer must retry via the UI.")
