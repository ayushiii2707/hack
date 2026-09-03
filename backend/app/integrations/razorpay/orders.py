"""Razorpay order helpers – payload construction + response normalization."""
from __future__ import annotations

from app.integrations.razorpay.client import RazorpayClient


def create_order(
    client: RazorpayClient, *, amount_paise: int, currency: str, receipt: str, notes: dict | None = None
) -> dict:
    """Create a Razorpay order. ``amount_paise`` must already be in paise."""
    raw = client.create_order(
        amount=amount_paise, currency=currency, receipt=receipt, notes=notes
    )
    return {
        "razorpay_order_id": raw["id"],
        "amount": raw["amount"],
        "currency": raw["currency"],
        "status": raw.get("status"),
        "receipt": raw.get("receipt"),
    }
