"""Centralised enums and constants.

Keep every string that carries domain meaning here so it is never
re-typed (and mis-typed) across the codebase.
"""
from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    """Lifecycle of a single customer shopping interaction."""

    BROWSING = "BROWSING"
    CART_BUILDING = "CART_BUILDING"
    CART_REVIEW = "CART_REVIEW"
    UPSELL = "UPSELL"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    COMPLETED = "COMPLETED"


# Allowed forward transitions. A transition is legal if the target is in the
# set mapped from the current state. Re-entering the same state is always legal.
SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.BROWSING: {
        SessionState.BROWSING,
        SessionState.CART_BUILDING,
        SessionState.CART_REVIEW,
    },
    SessionState.CART_BUILDING: {
        SessionState.CART_BUILDING,
        SessionState.BROWSING,
        SessionState.CART_REVIEW,
    },
    SessionState.CART_REVIEW: {
        SessionState.CART_REVIEW,
        SessionState.CART_BUILDING,
        SessionState.UPSELL,
        SessionState.PAYMENT_PENDING,
    },
    SessionState.UPSELL: {
        SessionState.UPSELL,
        SessionState.CART_REVIEW,
        SessionState.CART_BUILDING,
        SessionState.PAYMENT_PENDING,
    },
    SessionState.PAYMENT_PENDING: {
        SessionState.PAYMENT_PENDING,
        SessionState.PAYMENT_FAILED,
        SessionState.COMPLETED,
        SessionState.CART_REVIEW,
        SessionState.CART_BUILDING,
    },
    SessionState.PAYMENT_FAILED: {
        SessionState.PAYMENT_FAILED,
        SessionState.PAYMENT_PENDING,
        SessionState.COMPLETED,
        SessionState.CART_REVIEW,
        SessionState.CART_BUILDING,
    },
    SessionState.COMPLETED: {SessionState.COMPLETED},
}


class CartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHECKOUT = "CHECKOUT"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    CREATED = "CREATED"
    ATTEMPTED = "ATTEMPTED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"


class AuditActor(str, Enum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    PAYMENT_PROVIDER = "PAYMENT_PROVIDER"


class AuditAction(str, Enum):
    PRODUCT_SEARCHED = "PRODUCT_SEARCHED"
    ITEM_ADDED = "ITEM_ADDED"
    ITEM_REMOVED = "ITEM_REMOVED"
    ITEM_QUANTITY_UPDATED = "ITEM_QUANTITY_UPDATED"
    UPSELL_SHOWN = "UPSELL_SHOWN"
    UPSELL_ACCEPTED = "UPSELL_ACCEPTED"
    UPSELL_DECLINED = "UPSELL_DECLINED"
    CHECKOUT_STARTED = "CHECKOUT_STARTED"
    CHECKOUT_CANCELLED = "CHECKOUT_CANCELLED"
    STOCK_RESERVED = "STOCK_RESERVED"
    STOCK_RELEASED = "STOCK_RELEASED"
    PAYMENT_ATTEMPTED = "PAYMENT_ATTEMPTED"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_VERIFICATION_FAILED = "PAYMENT_VERIFICATION_FAILED"
    PAYMENT_LINK_CREATED = "PAYMENT_LINK_CREATED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    CATALOG_SYNCED = "CATALOG_SYNCED"
    SESSION_CREATED = "SESSION_CREATED"
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    WEBHOOK_REJECTED = "WEBHOOK_REJECTED"


class UIActionType(str, Enum):
    SHOW_PRODUCTS = "SHOW_PRODUCTS"
    SHOW_CART = "SHOW_CART"
    SHOW_UPSELL = "SHOW_UPSELL"
    SHOW_CHECKOUT = "SHOW_CHECKOUT"
    SHOW_PAYMENT = "SHOW_PAYMENT"
    SHOW_ERROR = "SHOW_ERROR"


DEFAULT_CURRENCY = "INR"
CATALOG_SOURCE_DUMMYJSON = "dummyjson"
