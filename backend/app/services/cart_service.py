"""Cart business logic and the hard quantity / stock / lifecycle boundaries.

These checks are enforced here regardless of caller, so they hold even if a
future caller forgets the agent policy layer:
  * quantity: 1 .. MAX_ITEM_QUANTITY  (cap breach -> POLICY_BLOCKED audit)
  * stock: resulting quantity must be available now (final check is at checkout)
  * lifecycle: a cart that is not ACTIVE cannot be mutated (post-checkout lock)
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import AuditAction, AuditActor, CartStatus, SessionState
from app.core.exceptions import (
    CartNotFoundError,
    ConflictError,
    EmptyCartError,
    InvalidQuantityError,
    PolicyViolationError,
    ProductInactiveError,
)
from app.models.cart import Cart
from app.repositories.cart_repository import CartRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService
from app.services.product_service import ProductService


@dataclass
class CartIssue:
    product_id: str
    name: str
    code: str
    message: str


class CartService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CartRepository(db)
        self.sessions = SessionRepository(db)
        self.products = ProductService(db)
        self.audit = AuditService(db)

    def _bump_to_cart_building(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is not None and session.state == SessionState.BROWSING:
            self.sessions.set_state(session, SessionState.CART_BUILDING)

    # --- reads ---
    def get_cart(self, cart_id: str) -> Cart:
        cart = self.repo.get(cart_id)
        if cart is None:
            raise CartNotFoundError(f"Cart {cart_id} was not found.")
        return cart

    def get_cart_for_session(self, session_id: str) -> Cart:
        cart = self.repo.get_by_session(session_id)
        if cart is None:
            raise CartNotFoundError(f"No cart for session {session_id}.")
        return cart

    # --- guards ---
    def _assert_cart_mutable(self, cart: Cart) -> None:
        if cart.status != CartStatus.ACTIVE:
            raise ConflictError(
                "This cart is locked because checkout has started. "
                "Cancel checkout to change your cart.",
                details={"cart_status": cart.status.value},
            )
        session = self.sessions.get(cart.session_id)
        if session is not None and session.state in (
            SessionState.PAYMENT_PENDING,
            SessionState.COMPLETED,
        ):
            raise ConflictError(
                "Your cart cannot be changed while a payment is in progress.",
                details={"session_state": session.state.value},
            )

    def _assert_quantity_within_policy(
        self, quantity: int, *, cart_id: str, product_id: str, session_id: str | None
    ) -> None:
        if quantity < 1:
            raise InvalidQuantityError("Quantity must be at least 1.")
        if quantity > settings.max_item_quantity:
            self.audit.log_policy_block(
                reason=(
                    f"Requested quantity {quantity} exceeds the per-product maximum "
                    f"of {settings.max_item_quantity}."
                ),
                session_id=session_id,
                metadata={
                    "cart_id": cart_id,
                    "product_id": product_id,
                    "requested_quantity": quantity,
                    "max_quantity": settings.max_item_quantity,
                },
            )
            self.db.commit()
            raise PolicyViolationError(
                f"You can add at most {settings.max_item_quantity} of a product.",
                details={"max_quantity": settings.max_item_quantity},
            )

    # --- mutations ---
    def add_item(
        self, cart_id: str, product_id: str, quantity: int, *, actor: AuditActor = AuditActor.AGENT
    ) -> Cart:
        cart = self.get_cart(cart_id)
        self._assert_cart_mutable(cart)
        session_id = cart.session_id
        existing = self.repo.get_item(cart_id, product_id)
        resulting_qty = quantity + (existing.quantity if existing else 0)

        self._assert_quantity_within_policy(
            resulting_qty, cart_id=cart_id, product_id=product_id, session_id=session_id
        )
        product = self.products.assert_purchasable(product_id, resulting_qty)

        if existing:
            self.repo.set_item_quantity(existing, resulting_qty)
            action, reason = (
                AuditAction.ITEM_QUANTITY_UPDATED,
                f"Increased '{product.name}' to {resulting_qty} (added {quantity}).",
            )
        else:
            self.repo.add_item(cart_id, product_id, quantity, product.price)
            action, reason = (
                AuditAction.ITEM_ADDED,
                f"Added {quantity} x '{product.name}' at {product.price} paise each.",
            )

        self.audit.log_event(
            actor=actor,
            action=action,
            reason=reason,
            session_id=session_id,
            metadata={"product_id": product_id, "quantity": resulting_qty, "unit_price": product.price},
        )
        self._bump_to_cart_building(session_id)
        self.db.commit()
        self.db.refresh(cart)
        return cart

    def update_quantity(
        self,
        cart_id: str,
        product_id: str,
        quantity: int,
        *,
        actor: AuditActor = AuditActor.AGENT,
    ) -> Cart:
        cart = self.get_cart(cart_id)
        self._assert_cart_mutable(cart)
        item = self.repo.get_item(cart_id, product_id)
        if item is None:
            raise InvalidQuantityError("That product is not in the cart.")
        if quantity == 0:
            return self.remove_item(cart_id, product_id, actor=actor)

        self._assert_quantity_within_policy(
            quantity, cart_id=cart_id, product_id=product_id, session_id=cart.session_id
        )
        product = self.products.assert_purchasable(product_id, quantity)
        self.repo.set_item_quantity(item, quantity)
        self.audit.log_event(
            actor=actor,
            action=AuditAction.ITEM_QUANTITY_UPDATED,
            reason=f"Set '{product.name}' quantity to {quantity}.",
            session_id=cart.session_id,
            metadata={"product_id": product_id, "quantity": quantity},
        )
        self.db.commit()
        self.db.refresh(cart)
        return cart

    def remove_item(
        self, cart_id: str, product_id: str, *, actor: AuditActor = AuditActor.AGENT
    ) -> Cart:
        cart = self.get_cart(cart_id)
        self._assert_cart_mutable(cart)
        item = self.repo.get_item(cart_id, product_id)
        if item is None:
            raise InvalidQuantityError("That product is not in the cart.")
        name = item.product.name if item.product else product_id
        self.repo.remove_item(item)
        self.audit.log_event(
            actor=actor,
            action=AuditAction.ITEM_REMOVED,
            reason=f"Removed '{name}' from the cart.",
            session_id=cart.session_id,
            metadata={"product_id": product_id},
        )
        self.db.commit()
        self.db.refresh(cart)
        return cart

    def clear_cart(self, cart_id: str) -> Cart:
        cart = self.get_cart(cart_id)
        self.repo.clear(cart)
        self.db.commit()
        self.db.refresh(cart)
        return cart

    # --- validation (used by checkout) ---
    def validate_cart(self, cart_id: str, *, require_non_empty: bool = True) -> list[CartIssue]:
        cart = self.get_cart(cart_id)
        if require_non_empty and not cart.items:
            raise EmptyCartError("Your cart is empty.")

        issues: list[CartIssue] = []
        for item in cart.items:
            product = item.product
            if product is None:
                issues.append(CartIssue(item.product_id, item.product_id, "PRODUCT_MISSING",
                                        "This product no longer exists."))
                continue
            if not product.active:
                issues.append(CartIssue(product.id, product.name, "PRODUCT_INACTIVE",
                                        f"'{product.name}' is no longer available."))
            if product.stock < item.quantity:
                issues.append(CartIssue(product.id, product.name, "INSUFFICIENT_STOCK",
                                        f"Only {product.stock} of '{product.name}' left."))
        return issues

    def assert_cart_ready(self, cart_id: str) -> Cart:
        issues = self.validate_cart(cart_id, require_non_empty=True)
        if issues:
            raise ProductInactiveError(
                "Some items need attention before checkout.",
                details={"issues": [i.__dict__ for i in issues]},
            )
        return self.get_cart(cart_id)

    def set_status(self, cart_id: str, status: CartStatus) -> Cart:
        cart = self.get_cart(cart_id)
        self.repo.set_status(cart, status)
        self.db.commit()
        self.db.refresh(cart)
        return cart
