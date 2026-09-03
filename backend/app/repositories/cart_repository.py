"""Cart + cart-item persistence."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import CartStatus
from app.models.cart import Cart
from app.models.cart_item import CartItem


class CartRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, session_id: str) -> Cart:
        cart = Cart(session_id=session_id, status=CartStatus.ACTIVE)
        self.db.add(cart)
        self.db.flush()
        return cart

    def get(self, cart_id: str) -> Cart | None:
        return self.db.get(Cart, cart_id)

    def get_by_session(self, session_id: str) -> Cart | None:
        return self.db.execute(
            select(Cart).where(Cart.session_id == session_id)
        ).scalar_one_or_none()

    def get_item(self, cart_id: str, product_id: str) -> CartItem | None:
        return self.db.execute(
            select(CartItem).where(
                CartItem.cart_id == cart_id, CartItem.product_id == product_id
            )
        ).scalar_one_or_none()

    def add_item(self, cart_id: str, product_id: str, quantity: int, unit_price: int) -> CartItem:
        item = CartItem(
            cart_id=cart_id, product_id=product_id, quantity=quantity, unit_price=unit_price
        )
        self.db.add(item)
        self.db.flush()
        return item

    def set_item_quantity(self, item: CartItem, quantity: int) -> None:
        item.quantity = quantity
        self.db.flush()

    def remove_item(self, item: CartItem) -> None:
        self.db.delete(item)
        self.db.flush()

    def clear(self, cart: Cart) -> None:
        for item in list(cart.items):
            self.db.delete(item)
        self.db.flush()

    def set_status(self, cart: Cart, status: CartStatus) -> None:
        cart.status = status
        self.db.flush()
