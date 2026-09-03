"""Razorpay Payment Link helpers."""
from __future__ import annotations

from app.integrations.razorpay.client import RazorpayClient


def create_payment_link(
    client: RazorpayClient,
    *,
    amount_paise: int,
    currency: str,
    description: str,
    reference_id: str,
    customer: dict | None = None,
    callback_url: str | None = None,
    notes: dict | None = None,
) -> dict:
    payload: dict = {
        "amount": int(amount_paise),
        "currency": currency,
        "accept_partial": False,
        "description": description[:2048],
        "reference_id": reference_id,
        "reminder_enable": True,
        "notify": {"sms": False, "email": bool(customer and customer.get("email"))},
        "notes": notes or {},
    }
    if customer:
        payload["customer"] = {
            k: v for k, v in customer.items() if k in ("name", "email", "contact") and v
        }
    if callback_url:
        payload["callback_url"] = callback_url
        payload["callback_method"] = "get"

    raw = client.create_payment_link(payload)
    return {
        "payment_link_id": raw["id"],
        "short_url": raw["short_url"],
        "status": raw.get("status"),
        "amount": raw.get("amount"),
        "reference_id": raw.get("reference_id"),
    }
