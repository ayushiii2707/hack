import pytest

from app.core.constants import CartStatus, OrderStatus, SessionState
from app.core.exceptions import CheckoutValidationError
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.session_service import SessionService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def session_obj(db_session):
    return SessionService(db_session).create_session()


def test_confirm_empty_cart_rejected(db_session, session_obj):
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)


def test_confirm_creates_order_with_server_side_amount(db_session, session_obj):
    p = make_product(db_session, price=249900, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    order = CheckoutService(db_session).confirm_checkout(session_obj.id)
    assert order.amount == 249900  # subtotal >= free-shipping threshold
    assert order.status == OrderStatus.CREATED
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


def test_confirm_blocked_while_upsell_pending(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    UpsellService(db_session).generate_recommendation(session_obj.id)  # shown, not resolved
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)
    UpsellService(db_session).decline(session_obj.id)
    order = CheckoutService(db_session).confirm_checkout(session_obj.id)
    assert order.amount == 280000


def test_invalid_stock_blocks_confirm(db_session, session_obj):
    p = make_product(db_session, price=100000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 3)
    p.stock = 1
    db_session.commit()
    with pytest.raises(CheckoutValidationError):
        CheckoutService(db_session).confirm_checkout(session_obj.id)


def test_review_reports_upsell_opportunity(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    review = CheckoutService(db_session).start_checkout(session_obj.id)
    assert review.upsell_available is True
    assert review.breakdown.total == 280000


def test_checkout_api_flow(client, db_session):
    p = make_product(db_session, price=150000, stock=10)
    sid = client.post("/sessions").json()["session_id"]
    cid = client.get(f"/sessions/{sid}").json()["cart_id"]
    client.post(f"/cart/{cid}/items", json={"product_id": p.id, "quantity": 1})
    r = client.post(f"/checkout/{sid}/review")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["total"] == 150500  # + ₹5 shipping (below threshold)
    c = client.post(f"/checkout/{sid}/confirm")
    assert c.status_code == 200
    assert c.json()["order"]["amount"] == 150500
