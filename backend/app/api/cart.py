"""Cart APIs. The cart is derived from the authenticated session — never from a
path id — so there is no cross-session access. Every mutation goes through
CartService, which also enforces the post-checkout lock.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_session
from app.core.constants import AuditActor
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.cart import AddItemIn, CartOut, UpdateQuantityIn
from app.services.cart_service import CartService
from app.services.pricing_service import PricingService

router = APIRouter(prefix="/cart", tags=["cart"])


def _cart_out(db: Session, session: ShopSession) -> CartOut:
    cart = CartService(db).get_cart_for_session(session.id)
    breakdown = PricingService(db).get_price_breakdown(cart.id)
    return CartOut.build(cart, breakdown)


@router.get("", response_model=CartOut, summary="View my cart with authoritative totals")
def get_cart(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return _cart_out(db, session)


@router.post("/items", response_model=CartOut, summary="Add an item to my cart")
def add_item(
    body: AddItemIn,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    cart = CartService(db).get_cart_for_session(session.id)
    CartService(db).add_item(cart.id, body.product_id, body.quantity, actor=AuditActor.CUSTOMER)
    return _cart_out(db, session)


@router.patch("/items/{product_id}", response_model=CartOut, summary="Set an item's quantity")
def update_item(
    product_id: str,
    body: UpdateQuantityIn,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    cart = CartService(db).get_cart_for_session(session.id)
    CartService(db).update_quantity(cart.id, product_id, body.quantity, actor=AuditActor.CUSTOMER)
    return _cart_out(db, session)


@router.delete("/items/{product_id}", response_model=CartOut, summary="Remove an item")
def remove_item(
    product_id: str,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    cart = CartService(db).get_cart_for_session(session.id)
    CartService(db).remove_item(cart.id, product_id, actor=AuditActor.CUSTOMER)
    return _cart_out(db, session)
