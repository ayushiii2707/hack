import pytest

from app.core.constants import AuditAction, CartStatus
from app.core.exceptions import (
    ConflictError,
    EmptyCartError,
    InsufficientStockError,
    PolicyViolationError,
)
from app.models.audit_log import AuditLog
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def cart_id(shop):
    return shop.session.cart.id


def test_add_item_snapshots_price(db_session, cart_id):
    p = make_product(db_session, price=249900, stock=10)
    svc = CartService(db_session)
    cart = svc.add_item(cart_id, p.id, 2)
    assert cart.items[0].unit_price == 249900
    p.price = 300000
    db_session.commit()
    assert svc.get_cart(cart_id).items[0].unit_price == 249900


def test_add_item_beyond_max_quantity_is_blocked_and_audited(db_session, cart_id):
    p = make_product(db_session, stock=100000)
    with pytest.raises(PolicyViolationError):
        CartService(db_session).add_item(cart_id, p.id, 999999)
    blocks = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.POLICY_BLOCKED
    ).count()
    assert blocks == 1
    assert CartService(db_session).get_cart(cart_id).items == []


def test_incremental_add_cannot_exceed_cap(db_session, cart_id):
    p = make_product(db_session, stock=100)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 3)
    with pytest.raises(PolicyViolationError):
        svc.add_item(cart_id, p.id, 3)


def test_add_item_insufficient_stock(db_session, cart_id):
    p = make_product(db_session, stock=1)
    with pytest.raises(InsufficientStockError):
        CartService(db_session).add_item(cart_id, p.id, 2)


def test_update_quantity_zero_removes(db_session, cart_id):
    p = make_product(db_session, stock=10)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 2)
    assert svc.update_quantity(cart_id, p.id, 0).items == []


def test_remove_item(db_session, cart_id):
    p = make_product(db_session, stock=10)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 1)
    assert svc.remove_item(cart_id, p.id).items == []


def test_validate_empty_cart_raises(db_session, cart_id):
    with pytest.raises(EmptyCartError):
        CartService(db_session).validate_cart(cart_id)


def test_validate_cart_flags_inactive_and_stock(db_session, cart_id):
    p = make_product(db_session, stock=10)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 3)
    p.active = False
    p.stock = 1
    db_session.commit()
    codes = {i.code for i in svc.validate_cart(cart_id)}
    assert "PRODUCT_INACTIVE" in codes and "INSUFFICIENT_STOCK" in codes


def test_cart_locked_after_checkout_confirm(db_session, shop):
    cart_id = shop.session.cart.id
    p = make_product(db_session, price=150000, stock=10)
    CartService(db_session).add_item(cart_id, p.id, 1)
    CheckoutService(db_session).confirm_checkout(shop.session.id)
    with pytest.raises(ConflictError):
        CartService(db_session).add_item(cart_id, p.id, 1)


def test_cart_unlocked_after_cancel(db_session, shop):
    cart_id = shop.session.cart.id
    p = make_product(db_session, price=150000, stock=10)
    CartService(db_session).add_item(cart_id, p.id, 1)
    CheckoutService(db_session).confirm_checkout(shop.session.id)
    CheckoutService(db_session).cancel_checkout(shop.session.id)
    cart = CartService(db_session).add_item(cart_id, p.id, 1)  # works again
    assert cart.status == CartStatus.ACTIVE
    assert cart.items[0].quantity == 2


# ---- API-level (authorised, session-scoped) ----
def test_cart_api_flow(api, db_session):
    p = make_product(db_session, price=100000, stock=10)
    r = api.post("/cart/items", json={"product_id": p.id, "quantity": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["subtotal"] == 200000


def test_cart_api_quantity_abuse_blocked_and_audited(api, db_session):
    p = make_product(db_session, stock=100000)
    r = api.post("/cart/items", json={"product_id": p.id, "quantity": 999999})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "POLICY_VIOLATION"
    assert db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.POLICY_BLOCKED
    ).count() == 1
    assert api.get("/cart").json()["items"] == []


def test_cart_api_requires_auth(client, db_session):
    p = make_product(db_session, stock=10)
    assert client.get("/cart").status_code == 401
    assert client.post("/cart/items", json={"product_id": p.id, "quantity": 1}).status_code == 401
