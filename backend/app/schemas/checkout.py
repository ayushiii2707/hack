"""Checkout API schemas."""
from __future__ import annotations

from pydantic import BaseModel

from app.models.order import Order
from app.schemas.cart import CartLineOut, CartTotalsOut
from app.services.checkout_service import CheckoutReview
from app.services.pricing_service import PriceBreakdown
from app.utils.money import format_inr


def _totals(b: PriceBreakdown) -> CartTotalsOut:
    return CartTotalsOut(
        currency=b.currency,
        subtotal=b.subtotal,
        shipping=b.shipping,
        tax=b.tax,
        total=b.total,
        subtotal_display=format_inr(b.subtotal),
        shipping_display=format_inr(b.shipping),
        total_display=format_inr(b.total),
        free_shipping_threshold=b.free_shipping_threshold,
        free_shipping_applied=b.free_shipping_applied,
    )


class CheckoutReviewOut(BaseModel):
    session_id: str
    cart_id: str
    items: list[CartLineOut]
    totals: CartTotalsOut
    upsell_available: bool
    upsell_pending: bool
    issues: list[dict]
    ready_for_payment: bool
    has_open_order: bool = False

    @classmethod
    def from_review(cls, r: CheckoutReview) -> CheckoutReviewOut:
        b = r.breakdown
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
            for li in b.line_items
        ]
        return cls(
            session_id=r.session_id,
            cart_id=r.cart_id,
            items=items,
            totals=_totals(b),
            upsell_available=r.upsell_available,
            upsell_pending=r.upsell_pending,
            issues=r.issues,
            ready_for_payment=(not r.issues and not r.upsell_pending and b.total > 0),
            has_open_order=r.has_open_order,
        )


class OrderOut(BaseModel):
    order_id: str
    session_id: str
    cart_id: str
    status: str
    amount: int
    amount_display: str
    currency: str
    subtotal: int
    shipping: int
    tax: int
    razorpay_order_id: str | None = None
    receipt: str | None = None

    @classmethod
    def from_model(cls, o: Order) -> OrderOut:
        return cls(
            order_id=o.id,
            session_id=o.session_id,
            cart_id=o.cart_id,
            status=o.status.value,
            amount=o.amount,
            amount_display=format_inr(o.amount),
            currency=o.currency,
            subtotal=o.subtotal,
            shipping=o.shipping,
            tax=o.tax,
            razorpay_order_id=o.razorpay_order_id,
            receipt=o.receipt,
        )


class ConfirmCheckoutOut(BaseModel):
    order: OrderOut
    payment: dict | None = None  # populated in Phase 7 (Razorpay init data)
