import pytest

from app.services.cart_service import CartService
from app.services.pricing_service import PricingService
from tests.factories import make_product


@pytest.fixture()
def cart_id(shop):
    return shop.session.cart.id


def test_subtotal_is_integer_paise(db_session, cart_id):
    p = make_product(db_session, price=124950, stock=10)
    CartService(db_session).add_item(cart_id, p.id, 3)
    b = PricingService(db_session).get_price_breakdown(cart_id)
    assert b.subtotal == 374850
    assert isinstance(b.subtotal, int)


def test_shipping_charged_below_threshold(db_session, cart_id):
    p = make_product(db_session, price=50000, stock=10)
    CartService(db_session).add_item(cart_id, p.id, 1)
    b = PricingService(db_session).get_price_breakdown(cart_id)
    assert b.shipping == 500
    assert b.total == 50500
    assert b.free_shipping_applied is False


def test_free_shipping_at_or_above_threshold(db_session, cart_id):
    p = make_product(db_session, price=200000, stock=10)
    CartService(db_session).add_item(cart_id, p.id, 1)
    b = PricingService(db_session).get_price_breakdown(cart_id)
    assert b.shipping == 0
    assert b.total == 200000
    assert b.free_shipping_applied is True


def test_empty_cart_has_zero_shipping(db_session, cart_id):
    b = PricingService(db_session).get_price_breakdown(cart_id)
    assert b.subtotal == 0 and b.shipping == 0 and b.total == 0


def test_tax_is_zero_v1(db_session, cart_id):
    p = make_product(db_session, price=99999, stock=5)
    CartService(db_session).add_item(cart_id, p.id, 1)
    b = PricingService(db_session).get_price_breakdown(cart_id)
    assert b.tax == 0
    assert b.total == b.subtotal + b.shipping
