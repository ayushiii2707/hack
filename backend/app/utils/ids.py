"""Prefixed, URL-safe identifiers.

We never expose raw auto-increment integers. Each entity gets a short
type-prefixed random id (e.g. ``prod_a1b2c3...``) so ids are self-describing
in logs and API responses.
"""
from __future__ import annotations

import uuid

_PREFIXES = {
    "product": "prod",
    "session": "sess",
    "cart": "cart",
    "cart_item": "citm",
    "order": "ord",
    "payment": "pay",
    "audit": "aud",
    "receipt": "rcpt",
}


def new_id(kind: str) -> str:
    prefix = _PREFIXES.get(kind, kind[:4])
    return f"{prefix}_{uuid.uuid4().hex}"


def product_id() -> str:
    return new_id("product")


def session_id() -> str:
    return new_id("session")


def cart_id() -> str:
    return new_id("cart")


def cart_item_id() -> str:
    return new_id("cart_item")


def order_id() -> str:
    return new_id("order")


def payment_id() -> str:
    return new_id("payment")


def audit_id() -> str:
    return new_id("audit")


def receipt_id() -> str:
    # Razorpay receipt field is limited to 40 chars.
    return f"rcpt_{uuid.uuid4().hex[:32]}"
