"""Razorpay payment helpers – signature verification + status normalization."""
from __future__ import annotations

from app.integrations.razorpay.client import RazorpayClient

# Razorpay payment.status -> our PaymentStatus name
RZP_STATUS_MAP = {
    "created": "CREATED",
    "authorized": "AUTHORIZED",
    "captured": "CAPTURED",
    "refunded": "CAPTURED",
    "failed": "FAILED",
}


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


def fetch_payment_status(client: RazorpayClient, razorpay_payment_id: str) -> dict:
    raw = client.fetch_payment(razorpay_payment_id)
    return {
        "razorpay_payment_id": raw.get("id"),
        "razorpay_order_id": raw.get("order_id"),
        "status": raw.get("status"),
        "mapped_status": RZP_STATUS_MAP.get(raw.get("status", ""), "FAILED"),
        "amount": raw.get("amount"),
        "method": raw.get("method"),
        "error_code": raw.get("error_code"),
        "error_description": raw.get("error_description"),
    }
