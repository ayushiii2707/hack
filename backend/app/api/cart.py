"""Cart APIs. Every mutation goes through CartService – never raw SQL here."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.constants import AuditActor
from app.database.database import get_db
from app.schemas.cart import AddItemIn, CartOut, UpdateQuantityIn
from app.services.cart_service import CartService
from app.services.pricing_service import PricingService

router = APIRouter(prefix="/cart", tags=["cart"])


def _cart_out(db: Session, cart_id: str) -> CartOut:
    cart = CartService(db).get_cart(cart_id)
    breakdown = PricingService(db).get_price_breakdown(cart_id)
    return CartOut.build(cart, breakdown)


@router.get("/{cart_id}", response_model=CartOut, summary="View cart with authoritative totals")
def get_cart(cart_id: str, db: Session = Depends(get_db)):
    return _cart_out(db, cart_id)


@router.post("/{cart_id}/items", response_model=CartOut, summary="Add an item to the cart")
def add_item(cart_id: str, body: AddItemIn, db: Session = Depends(get_db)):
    CartService(db).add_item(cart_id, body.product_id, body.quantity, actor=AuditActor.CUSTOMER)
    return _cart_out(db, cart_id)


@router.patch(
    "/{cart_id}/items/{product_id}", response_model=CartOut, summary="Set an item's quantity"
)
def update_item(
    cart_id: str, product_id: str, body: UpdateQuantityIn, db: Session = Depends(get_db)
):
    CartService(db).update_quantity(
        cart_id, product_id, body.quantity, actor=AuditActor.CUSTOMER
    )
    return _cart_out(db, cart_id)


@router.delete("/{cart_id}/items/{product_id}", response_model=CartOut, summary="Remove an item")
def remove_item(cart_id: str, product_id: str, db: Session = Depends(get_db)):
    CartService(db).remove_item(cart_id, product_id, actor=AuditActor.CUSTOMER)
    return _cart_out(db, cart_id)
