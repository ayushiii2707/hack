"""The deterministic fallback agent (used when GEMINI_API_KEY is unset)."""
from __future__ import annotations

import pytest

from app.agent.agent import run_agent
from app.services.cart_service import CartService
from tests.factories import make_product


@pytest.fixture()
def session_obj(shop):
    return shop.session


@pytest.fixture(autouse=True)
def _no_gemini(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", "", raising=False)


def test_fallback_search_with_price_filter(db_session, session_obj):
    make_product(db_session, external_id="x1", name="Velocity Running Shoes",
                 category="mens-shoes", price=280000, stock=5, tags=["running", "shoes"])
    make_product(db_session, external_id="x2", name="Premium Trail Shoes",
                 category="mens-shoes", price=900000, stock=5, tags=["running", "shoes"])
    resp = run_agent(db_session, session_id=session_obj.id, message="show me running shoes under 3000")
    assert "search_products" in resp.tool_calls
    show = [a for a in resp.actions if a.type == "SHOW_PRODUCTS"][0]
    assert len(show.payload["product_ids"]) == 1


def test_fallback_checkout_intent(db_session, session_obj):
    p = make_product(db_session, external_id="x3", name="Shoes", price=150000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    resp = run_agent(db_session, session_id=session_obj.id, message="I'm ready to check out")
    assert "start_checkout" in resp.tool_calls
    assert any(a.type == "SHOW_CHECKOUT" for a in resp.actions)


def test_fallback_cart_intent(db_session, session_obj):
    p = make_product(db_session, external_id="x4", name="Shoes", price=150000, stock=5)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 2)
    resp = run_agent(db_session, session_id=session_obj.id, message="show me my cart")
    assert "get_cart" in resp.tool_calls
    assert "2x Shoes" in resp.message
