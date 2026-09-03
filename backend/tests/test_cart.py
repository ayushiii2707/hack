import pytest

from app.core.constants import AuditAction
from app.core.exceptions import (
    EmptyCartError,
    InsufficientStockError,
    InvalidQuantityError,
    PolicyViolationError,
)
from app.models.audit_log import AuditLog
from app.services.cart_service import CartService
from app.services.session_service import SessionService
from tests.factories import make_product


@pytest.fixture()
def session_obj(db_session):
    return SessionService(db_session).create_session()


@pytest.fixture()
def cart_id(session_obj):
    return session_obj.cart.id


def test_add_item_snapshots_price(db_session, cart_id):
    p = make_product(db_session, price=249900, stock=10)
    svc = CartService(db_session)
    cart = svc.add_item(cart_id, p.id, 2)
    assert cart.items[0].unit_price == 249900
    assert cart.items[0].quantity == 2
    # price snapshot survives a later catalog price change
    p.price = 300000
    db_session.commit()
    assert svc.get_cart(cart_id).items[0].unit_price == 249900


def test_add_item_beyond_max_quantity_is_blocked_and_audited(db_session, cart_id):
    p = make_product(db_session, stock=100000)
    svc = CartService(db_session)
    with pytest.raises(PolicyViolationError):
        svc.add_item(cart_id, p.id, 999999)
    blocks = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == AuditAction.POLICY_BLOCKED)
        .all()
    )
    assert len(blocks) == 1
    assert svc.get_cart(cart_id).items == []


def test_incremental_add_cannot_exceed_cap(db_session, cart_id):
    p = make_product(db_session, stock=100)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 3)
    with pytest.raises(PolicyViolationError):
        svc.add_item(cart_id, p.id, 3)  # 3 + 3 = 6 > max 5


def test_add_item_insufficient_stock(db_session, cart_id):
    p = make_product(db_session, stock=1)
    with pytest.raises(InsufficientStockError):
        CartService(db_session).add_item(cart_id, p.id, 2)


def test_update_quantity_zero_removes(db_session, cart_id):
    p = make_product(db_session, stock=10)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 2)
    cart = svc.update_quantity(cart_id, p.id, 0)
    assert cart.items == []


def test_remove_item(db_session, cart_id):
    p = make_product(db_session, stock=10)
    svc = CartService(db_session)
    svc.add_item(cart_id, p.id, 1)
    cart = svc.remove_item(cart_id, p.id)
    assert cart.items == []


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
    issues = svc.validate_cart(cart_id)
    codes = {i.code for i in issues}
    assert "PRODUCT_INACTIVE" in codes and "INSUFFICIENT_STOCK" in codes


def test_cart_api_flow(client, db_session):
    p = make_product(db_session, price=100000, stock=10)
    s = client.post("/sessions").json()
    cart_id = s["cart_id"]
    r = client.post(f"/cart/{cart_id}/items", json={"product_id": p.id, "quantity": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["subtotal"] == 200000
    assert isinstance(body["totals"]["total"], int)


def test_cart_api_quantity_abuse_returns_structured_error(client, db_session):
    p = make_product(db_session, stock=100000)
    cart_id = client.post("/sessions").json()["cart_id"]
    r = client.post(f"/cart/{cart_id}/items", json={"product_id": p.id, "quantity": 999999})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "POLICY_VIOLATION"
