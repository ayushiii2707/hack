"""Cart API schemas. Totals always come from the backend PricingService."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.cart import Cart
from app.services.pricing_service import PriceBreakdown
from app.utils.money import format_inr


class CartLineOut(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price: int
    unit_price_display: str
    line_total: int
    line_total_display: str


class CartTotalsOut(BaseModel):
    currency: str
    subtotal: int
    shipping: int
    tax: int
    total: int
    subtotal_display: str
    shipping_display: str
    total_display: str
    free_shipping_threshold: int
    free_shipping_applied: bool


class CartOut(BaseModel):
    cart_id: str
    session_id: str
    status: str
    items: list[CartLineOut]
    totals: CartTotalsOut

    @classmethod
    def build(cls, cart: Cart, breakdown: PriceBreakdown) -> "CartOut":
        items = [
            CartLineOut(
                product_id=li.product_id,
                name=li.name,
                quantity=li.quantity,
                unit_price=li.unit_price,
                unit_price_display=format_inr(li.unit_price),
                line_total=li.line_total,
                line_total_display=format_inr(li.line_total),
            )
            for li in breakdown.line_items
        ]
        totals = CartTotalsOut(
            currency=breakdown.currency,
            subtotal=breakdown.subtotal,
            shipping=breakdown.shipping,
            tax=breakdown.tax,
            total=breakdown.total,
            subtotal_display=format_inr(breakdown.subtotal),
            shipping_display=format_inr(breakdown.shipping),
            total_display=format_inr(breakdown.total),
            free_shipping_threshold=breakdown.free_shipping_threshold,
            free_shipping_applied=breakdown.free_shipping_applied,
        )
        return cls(
            cart_id=cart.id,
            session_id=cart.session_id,
            status=cart.status.value,
            items=items,
            totals=totals,
        )


class AddItemIn(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)


class UpdateQuantityIn(BaseModel):
    quantity: int = Field(ge=0)
