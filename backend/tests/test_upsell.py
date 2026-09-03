import pytest

from app.core.constants import AuditAction
from app.core.exceptions import UpsellAlreadyShownError, UpsellNotAvailableError
from app.models.audit_log import AuditLog
from app.services.cart_service import CartService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def session_obj(shop):
    return shop.session


def _anchor_and_addon(db_session, anchor_price=280000, addon_price=15000):
    anchor = make_product(
        db_session, external_id="a", name="Velocity Running Shoes", category="mens-shoes",
        brand="Velocity", price=anchor_price, stock=20, tags=["running", "shoes"],
    )
    addon = make_product(
        db_session, external_id="b", name="Running Socks", category="mens-shoes",
        brand="Velocity", price=addon_price, stock=50, tags=["running", "socks"],
    )
    return anchor, addon


def test_relevant_candidate_within_cap_is_selected(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    reco = UpsellService(db_session).generate_recommendation(session_obj.id)
    assert reco.product.id == addon.id
    assert reco.product.price <= reco.price_cap


def test_candidate_over_price_cap_is_rejected(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Velocity Running Shoes",
                          category="mens-shoes", brand="Velocity", price=250000, stock=20,
                          tags=["running", "shoes"])
    make_product(db_session, external_id="c", name="Pricey Watch", category="mens-shoes",
                 price=150000, stock=5, tags=["watch"])
    make_product(db_session, external_id="d", name="Cheap Laces", category="mens-shoes",
                 price=9000, stock=5, tags=["laces"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    reco = UpsellService(db_session).generate_recommendation(session_obj.id)
    assert reco.product.name == "Cheap Laces"
    assert reco.product.price <= reco.price_cap


def test_price_cap_boundary_exact(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=250000, stock=10, tags=["running"])
    # cap is 20% of 250000 = 50000 -> exactly-at-cap must be allowed
    make_product(db_session, external_id="b", name="At Cap", category="mens-shoes",
                 price=50000, stock=10, tags=["running"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    reco = UpsellService(db_session).generate_recommendation(session_obj.id)
    assert reco.product.name == "At Cap"


def test_out_of_stock_candidate_excluded(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    addon.stock = 0
    db_session.commit()
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    with pytest.raises(UpsellNotAvailableError):
        UpsellService(db_session).generate_recommendation(session_obj.id)
    db_session.refresh(session_obj)
    assert session_obj.upsell_shown is True


def test_candidate_already_in_cart_excluded(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    CartService(db_session).add_item(session_obj.cart.id, addon.id, 1)
    with pytest.raises(UpsellNotAvailableError):
        UpsellService(db_session).generate_recommendation(session_obj.id)


def test_exactly_one_upsell_per_session(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    svc = UpsellService(db_session)
    svc.generate_recommendation(session_obj.id)
    with pytest.raises(UpsellAlreadyShownError):
        svc.generate_recommendation(session_obj.id)


def test_decline_prevents_second_upsell(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    svc = UpsellService(db_session)
    svc.generate_recommendation(session_obj.id)
    svc.decline(session_obj.id)
    with pytest.raises(UpsellAlreadyShownError):
        svc.generate_recommendation(session_obj.id)


def test_cart_change_after_upsell_does_not_reset(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    extra = make_product(db_session, external_id="e", name="Water Bottle",
                         category="sports-accessories", price=12000, stock=10, tags=["hydration"])
    svc = UpsellService(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    svc.generate_recommendation(session_obj.id)
    svc.decline(session_obj.id)
    CartService(db_session).add_item(session_obj.cart.id, extra.id, 1)
    assert svc.peek(session_obj.id) is None
    with pytest.raises(UpsellAlreadyShownError):
        svc.generate_recommendation(session_obj.id)


def test_accepted_upsell_is_audited(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    svc = UpsellService(db_session)
    svc.generate_recommendation(session_obj.id)
    svc.accept(session_obj.id)
    actions = {a.action for a in db_session.query(AuditLog).all()}
    assert AuditAction.UPSELL_SHOWN in actions
    assert AuditAction.UPSELL_ACCEPTED in actions


def test_peek_does_not_consume_guard(db_session, session_obj):
    anchor, addon = _anchor_and_addon(db_session)
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    svc = UpsellService(db_session)
    assert svc.peek(session_obj.id) is not None
    db_session.refresh(session_obj)
    assert session_obj.upsell_shown is False
    assert svc.generate_recommendation(session_obj.id) is not None


def test_upsell_api_flow(api, db_session):
    anchor, addon = _anchor_and_addon(db_session)
    api.post("/cart/items", json={"product_id": anchor.id, "quantity": 1})
    r = api.post("/upsell")
    assert r.status_code == 200 and r.json()["available"] is True
    r2 = api.post("/upsell")
    assert r2.json()["available"] is False


def test_upsell_api_requires_auth(client):
    assert client.post("/upsell").status_code == 401
