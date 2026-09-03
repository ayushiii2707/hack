"""Authoritative price calculation. Backend owns this; the frontend displays
it and the LLM only explains it. Every value is integer paise.

V1: prices are tax-inclusive. No coupon / discount / tax engine.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import DEFAULT_CURRENCY
from app.models.cart import Cart
from app.services.cart_service import CartService


@dataclass
class LineItem:
    product_id: str
    name: str
    quantity: int
    unit_price: int
    line_total: int


@dataclass
class PriceBreakdown:
    currency: str
    line_items: list[LineItem]
    subtotal: int
    shipping: int
    tax: int
    total: int
    free_shipping_threshold: int
    free_shipping_applied: bool

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "subtotal": self.subtotal,
            "shipping": self.shipping,
            "tax": self.tax,
            "total": self.total,
            "free_shipping_threshold": self.free_shipping_threshold,
            "free_shipping_applied": self.free_shipping_applied,
            "line_items": [li.__dict__ for li in self.line_items],
        }


class PricingService:
    def __init__(self, db: Session):
        self.db = db
        self.carts = CartService(db)

    def _line_items(self, cart: Cart) -> list[LineItem]:
        items = []
        for it in cart.items:
            name = it.product.name if it.product else it.product_id
            items.append(
                LineItem(
                    product_id=it.product_id,
                    name=name,
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    line_total=it.unit_price * it.quantity,
                )
            )
        return items

    def calculate_subtotal(self, cart: Cart) -> int:
        return sum(it.unit_price * it.quantity for it in cart.items)

    def calculate_shipping(self, subtotal: int) -> int:
        if subtotal <= 0:
            return 0
        if subtotal >= settings.free_shipping_threshold:
            return 0
        return settings.shipping_fee

    def calculate_tax(self, subtotal: int) -> int:  # V1: tax-inclusive pricing
        return 0

    def get_price_breakdown(self, cart_id: str) -> PriceBreakdown:
        cart = self.carts.get_cart(cart_id)
        line_items = self._line_items(cart)
        subtotal = sum(li.line_total for li in line_items)
        shipping = self.calculate_shipping(subtotal)
        tax = self.calculate_tax(subtotal)
        total = subtotal + shipping + tax
        return PriceBreakdown(
            currency=DEFAULT_CURRENCY,
            line_items=line_items,
            subtotal=subtotal,
            shipping=shipping,
            tax=tax,
            total=total,
            free_shipping_threshold=settings.free_shipping_threshold,
            free_shipping_applied=subtotal > 0 and shipping == 0,
        )

    def calculate_total(self, cart_id: str) -> int:
        return self.get_price_breakdown(cart_id).total
