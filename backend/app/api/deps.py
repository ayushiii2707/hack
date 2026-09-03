"""Shared FastAPI dependencies: session authentication, ownership, admin auth.

Identity model: anonymous sessions, each holding an opaque bearer token
(``Authorization: Bearer <token>`` or the ``cc_session`` cookie). Ownership of a
cart / order / payment is always derived from the authenticated session — path
ids are validated against it, never trusted on their own. A non-owned id yields
the same 404 as a non-existent one (no enumeration oracle).
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.context import set_context_session_id
from app.core.exceptions import (
    AuthenticationError,
    CartNotFoundError,
    ForbiddenError,
    OrderNotFoundError,
)
from app.database.database import get_db
from app.models.order import Order
from app.models.payment import Payment
from app.models.session import Session as ShopSession
from app.repositories.cart_repository import CartRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.session_service import SessionService


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(settings.session_cookie_name, "").strip()


def require_session(
    request: Request, db: Session = Depends(get_db)
) -> ShopSession:
    token = _extract_token(request)
    session = SessionService(db).authenticate(token)
    if session is None:
        raise AuthenticationError("A valid session token is required.")
    set_context_session_id(session.id)
    return session


def optional_session(
    request: Request, db: Session = Depends(get_db)
) -> ShopSession | None:
    token = _extract_token(request)
    session = SessionService(db).authenticate(token) if token else None
    if session is not None:
        set_context_session_id(session.id)
    return session


def require_admin(request: Request) -> None:
    from app.core.security import verify_admin_key

    if not verify_admin_key(request.headers.get("x-admin-key")):
        raise ForbiddenError("Admin credentials required.")


# --- ownership resolvers ---
def owned_cart_id(session: ShopSession, db: Session, cart_id: str) -> str:
    cart = CartRepository(db).get(cart_id)
    if cart is None or cart.session_id != session.id:
        raise CartNotFoundError("Cart not found.")
    return cart_id


def owned_order(session: ShopSession, db: Session, order_id: str) -> Order:
    order = OrderRepository(db).get(order_id)
    if order is None or order.session_id != session.id:
        raise OrderNotFoundError("Order not found.")
    return order


def owned_payment(session: ShopSession, db: Session, payment_id: str) -> Payment:
    payment = PaymentRepository(db).get(payment_id)
    if payment is None:
        raise OrderNotFoundError("Payment not found.")
    order = OrderRepository(db).get(payment.order_id)
    if order is None or order.session_id != session.id:
        raise OrderNotFoundError("Payment not found.")
    return payment


def require_session_path_match(session: ShopSession, path_session_id: str) -> None:
    if path_session_id != session.id:
        raise ForbiddenError("This session id does not belong to you.")
