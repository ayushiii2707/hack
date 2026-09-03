"""Razorpay payment helpers – signature verification + reconciliation."""
from __future__ import annotations

from dataclasses import dataclass

from app.integrations.razorpay.client import RazorpayClient

# Razorpay payment.status -> our PaymentStatus name
RZP_STATUS_MAP = {
    "created": "CREATED",
    "authorized": "AUTHORIZED",
    "captured": "CAPTURED",
    "refunded": "CAPTURED",
    "failed": "FAILED",
}

# Statuses we treat as "money received" for an auto-capture order.
SETTLED_STATUSES = frozenset({"captured", "authorized"})


@dataclass
class GatewayPayment:
    payment_id: str
    order_id: str | None
    status: str
    amount: int | None
    currency: str | None
    method: str | None
    error_code: str | None
    error_description: str | None

    @property
    def is_settled(self) -> bool:
        return self.status in SETTLED_STATUSES


def verify_checkout_signature(
    client: RazorpayClient,
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> None:
    client.verify_payment_signature(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )


def fetch_payment(client: RazorpayClient, razorpay_payment_id: str) -> GatewayPayment:
    raw = client.fetch_payment(razorpay_payment_id)
    return GatewayPayment(
        payment_id=raw.get("id") or razorpay_payment_id,
        order_id=raw.get("order_id"),
        status=raw.get("status", ""),
        amount=raw.get("amount"),
        currency=raw.get("currency"),
        method=raw.get("method"),
        error_code=raw.get("error_code"),
        error_description=raw.get("error_description"),
    )
