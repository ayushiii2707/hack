import pytest

from app.core.constants import CartStatus, OrderStatus, SessionState
from app.core.exceptions import CheckoutValidationError
from app.repositories.product_repository import ProductRepository
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def session_obj(shop):
    return shop.session


def test_confirm_empty_cart_rejected(db_session, session_obj):
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)


def test_confirm_creates_order_with_server_side_amount_and_reserves_stock(db_session, session_obj):
    p = make_product(db_session, price=249900, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 2)
    order = CheckoutService(db_session).confirm_checkout(session_obj.id)
    assert order.amount == 499800
    assert order.status == OrderStatus.CREATED
    assert order.stock_reserved is True
    db_session.refresh(p)
    assert p.stock == 8  # reserved
    db_session.refresh(session_obj)
    assert session_obj.state == SessionState.PAYMENT_PENDING
    assert session_obj.cart.status == CartStatus.CHECKOUT


def test_confirm_is_idempotent(db_session, session_obj):
    p = make_product(db_session, price=100000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    svc = CheckoutService(db_session)
    o1 = svc.confirm_checkout(session_obj.id)
    o2 = svc.confirm_checkout(session_obj.id)
    assert o1.id == o2.id
    db_session.refresh(p)
    assert p.stock == 9  # only reserved once


def test_confirm_blocked_while_upsell_pending(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    UpsellService(db_session).generate_recommendation(session_obj.id)
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)
    UpsellService(db_session).decline(session_obj.id)
    assert CheckoutService(db_session).confirm_checkout(session_obj.id).amount == 280000


def test_insufficient_stock_blocks_confirm_and_reserves_nothing(db_session, session_obj):
    p1 = make_product(db_session, external_id="p1", price=100000, stock=5)
    p2 = make_product(db_session, external_id="p2", price=100000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p1.id, 3)
    CartService(db_session).add_item(session_obj.cart.id, p2.id, 3)
    ProductRepository(db_session).try_decrement_stock(p2.id, 4)  # only 1 left now
    db_session.commit()
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)
    db_session.refresh(p1)
    assert p1.stock == 5  # p1 reservation was rolled back


def test_cancel_releases_stock_and_order(db_session, session_obj):
    p = make_product(db_session, price=100000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 2)
    svc = CheckoutService(db_session)
    order = svc.confirm_checkout(session_obj.id)
    svc.cancel_checkout(session_obj.id)
    db_session.refresh(p)
    db_session.refresh(order)
    assert p.stock == 5
    assert order.status == OrderStatus.CANCELLED
    assert order.open_cart_key is None


def test_stock_reserve_and_release_are_independently_auditable(db_session, session_obj):
    from app.core.constants import AuditAction
    from app.models.audit_log import AuditLog

    p = make_product(db_session, price=100000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 2)
    svc = CheckoutService(db_session)
    order = svc.confirm_checkout(session_obj.id)

    reserved = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.STOCK_RESERVED, AuditLog.order_id == order.id
    ).all()
    assert len(reserved) == 1
    assert reserved[0].meta and "lines" in reserved[0].meta

    svc.cancel_checkout(session_obj.id)
    released = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.STOCK_RELEASED, AuditLog.order_id == order.id
    ).all()
    assert len(released) == 1


def test_checkout_api_flow(api, db_session):
    p = make_product(db_session, price=150000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    r = api.post("/checkout/review")
    assert r.status_code == 200
    assert r.json()["totals"]["total"] == 150500
    c = api.post("/checkout/confirm")
    assert c.status_code == 200
    assert c.json()["order"]["amount"] == 150500


def test_checkout_api_requires_auth(client):
    assert client.post("/checkout/confirm").status_code == 401
