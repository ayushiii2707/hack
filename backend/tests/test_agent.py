"""Agent orchestration + UI-action derivation tests (no network)."""
from __future__ import annotations

import pytest

from app.agent.agent import run_agent
from app.services.session_service import SessionService
from tests.factories import make_product
from tests.fake_llm import FakeToolCallingModel, final, tool_call


@pytest.fixture()
def session_obj(shop):
    return shop.session


def test_agent_search_builds_show_products_action(db_session, session_obj):
    make_product(db_session, external_id="s1", name="Velocity Running Shoes",
                 category="mens-shoes", price=280000, stock=10, tags=["running", "shoes"])
    model = FakeToolCallingModel(script=[
        tool_call("search_products", {"query": "running shoes", "max_price_rupees": 3000}),
        final("I found some running shoes for you."),
    ])
    resp = run_agent(db_session, session_id=session_obj.id, message="running shoes under 3000", model=model)
    assert "search_products" in resp.tool_calls
    show = [a for a in resp.actions if a.type == "SHOW_PRODUCTS"]
    assert show and len(show[0].payload["product_ids"]) == 1


def test_agent_add_to_cart_flow(db_session, session_obj):
    p = make_product(db_session, external_id="s2", name="Shoes", price=280000, stock=10)
    model = FakeToolCallingModel(script=[
        tool_call("add_to_cart", {"product_id": p.id, "quantity": 2}),
        final("Added 2 to your cart."),
    ])
    resp = run_agent(db_session, session_id=session_obj.id, message="add 2", model=model)
    assert any(a.type == "SHOW_CART" for a in resp.actions)
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert cart.items[0].quantity == 2


def test_agent_cannot_exceed_quantity_cap(db_session, session_obj):
    p = make_product(db_session, external_id="s3", name="Shoes", price=100000, stock=100000)
    model = FakeToolCallingModel(script=[
        tool_call("add_to_cart", {"product_id": p.id, "quantity": 999999}),
        final("I couldn't add that many."),
    ])
    run_agent(db_session, session_id=session_obj.id, message="add 999999", model=model)
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert cart.items == []


def test_agent_has_no_payment_tool(db_session, session_obj):
    from app.agent.tools import ToolContext, build_tools

    ctx = ToolContext(db=db_session, session_id=session_obj.id)
    names = {t.name for t in build_tools(ctx)}
    assert names == {
        "search_products", "get_product", "add_to_cart", "update_cart_quantity",
        "remove_from_cart", "get_cart", "calculate_total", "request_upsell",
        "accept_upsell", "decline_upsell", "start_checkout", "get_checkout_status",
    }
    assert not any("payment" in n for n in names)


def test_agent_second_upsell_is_blocked(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    from app.services.cart_service import CartService

    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    m1 = FakeToolCallingModel(script=[tool_call("request_upsell", {}), final("How about socks?")])
    r1 = run_agent(db_session, session_id=session_obj.id, message="anything else?", model=m1)
    assert any(a.type == "SHOW_UPSELL" for a in r1.actions)
    m2 = FakeToolCallingModel(script=[tool_call("request_upsell", {}), final("Nothing more.")])
    r2 = run_agent(db_session, session_id=session_obj.id, message="really?", model=m2)
    assert not any(a.type == "SHOW_UPSELL" for a in r2.actions)


def test_agent_persists_chat_history(db_session, session_obj):
    model = FakeToolCallingModel(script=[final("Hello! How can I help?")])
    run_agent(db_session, session_id=session_obj.id, message="hi", model=model)
    session = SessionService(db_session).get_session(session_obj.id)
    assert '"role": "user"' in session.chat_history
    assert "Hello" in session.chat_history


def test_agent_actions_only_use_known_types(db_session, session_obj):
    p = make_product(db_session, external_id="s4", name="Shoes", price=100000, stock=10)
    model = FakeToolCallingModel(script=[
        tool_call("get_product", {"product_id": p.id}),
        final("Here it is."),
    ])
    resp = run_agent(db_session, session_id=session_obj.id, message="show me that", model=model)
    allowed = {"SHOW_PRODUCTS", "SHOW_CART", "SHOW_UPSELL", "SHOW_CHECKOUT", "SHOW_PAYMENT", "SHOW_ERROR"}
    assert all(a.type in allowed for a in resp.actions)


def test_agent_falls_back_when_model_raises(db_session, session_obj):
    make_product(db_session, external_id="s5", name="Trail Shoes", category="mens-shoes",
                 price=200000, stock=5, tags=["shoes"])

    class Boom(FakeToolCallingModel):
        def _generate(self, *a, **k):
            raise RuntimeError("gemini exploded")

    resp = run_agent(db_session, session_id=session_obj.id, message="show me shoes",
                     model=Boom(script=[final("x")]))
    assert "search_products" in resp.tool_calls  # deterministic fallback still worked


# ---- deterministic fallback router: cart mutation by explicit product name ----
# (No GEMINI_API_KEY in the test environment -> run_agent(model=None) always
# takes the keyword-router path in app/agent/agent.py::_run_fallback.)

def test_fallback_adds_named_product_to_cart(db_session, session_obj):
    make_product(db_session, external_id="f1", name="Velocity Running Shoes",
                 price=280000, stock=10)
    resp = run_agent(db_session, session_id=session_obj.id,
                      message="add the Velocity Running Shoes to my cart")
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert [i.quantity for i in cart.items] == [1]
    assert "add_to_cart" in resp.tool_calls


def test_fallback_refuses_ambiguous_pronoun_add_without_mutating_cart(db_session, session_obj):
    make_product(db_session, external_id="f2", name="Velocity Running Shoes",
                 price=280000, stock=10)
    resp = run_agent(db_session, session_id=session_obj.id, message="add the first one to my cart")
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert cart.items == []  # never guesses which product "the first one" means
    assert "add_to_cart" not in resp.tool_calls
    assert "not sure which item" in resp.message.lower()


def test_fallback_updates_quantity_by_name(db_session, session_obj):
    from app.services.cart_service import CartService

    p = make_product(db_session, external_id="f3", name="Velocity Running Shoes",
                      price=280000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    run_agent(db_session, session_id=session_obj.id,
              message="set Velocity Running Shoes quantity to 3")
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert cart.items[0].quantity == 3


def test_fallback_removes_named_product_from_cart(db_session, session_obj):
    from app.services.cart_service import CartService

    p = make_product(db_session, external_id="f4", name="Velocity Running Shoes",
                      price=280000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    run_agent(db_session, session_id=session_obj.id,
              message="remove the Velocity Running Shoes from my cart")
    cart = SessionService(db_session).get_session(session_obj.id).cart
    assert cart.items == []


def test_fallback_how_much_reports_total_without_mutating_cart(db_session, session_obj):
    from app.services.cart_service import CartService

    p = make_product(db_session, external_id="f5", name="Shoes", price=280000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    resp = run_agent(db_session, session_id=session_obj.id, message="How much will I pay?")
    assert "get_cart" in resp.tool_calls
    assert any(a.type == "SHOW_CART" for a in resp.actions)


def test_fallback_decline_upsell_via_chat(db_session, session_obj):
    from app.services.cart_service import CartService
    from app.services.upsell_service import UpsellService

    anchor = make_product(db_session, external_id="f6a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="f6b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    UpsellService(db_session).generate_recommendation(session_obj.id)

    resp = run_agent(db_session, session_id=session_obj.id, message="No thanks, I'll decline that.")
    assert "decline_upsell" in resp.tool_calls
    session = SessionService(db_session).get_session(session_obj.id)
    assert session.upsell_declined is True
    assert session.upsell_accepted is False


def test_fallback_accept_upsell_via_chat(db_session, session_obj):
    from app.services.cart_service import CartService
    from app.services.upsell_service import UpsellService

    anchor = make_product(db_session, external_id="f7a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="f7b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    UpsellService(db_session).generate_recommendation(session_obj.id)

    resp = run_agent(db_session, session_id=session_obj.id, message="Sounds good, I'll take it.")
    assert "accept_upsell" in resp.tool_calls
    session = SessionService(db_session).get_session(session_obj.id)
    assert session.upsell_accepted is True


def test_fallback_recognizes_complementary_phrasing_for_upsell(db_session, session_obj):
    from app.services.cart_service import CartService

    anchor = make_product(db_session, external_id="f8a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="f8b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    resp = run_agent(db_session, session_id=session_obj.id,
                      message="Do you have anything complementary?")
    assert "request_upsell" in resp.tool_calls


def test_fallback_decline_upsell_before_any_upsell_shown_is_a_safe_error(db_session, session_obj):
    resp = run_agent(db_session, session_id=session_obj.id, message="no thanks, not interested")
    assert "decline_upsell" in resp.tool_calls
    session = SessionService(db_session).get_session(session_obj.id)
    assert session.upsell_declined is False  # nothing to decline yet; must not fabricate state
    assert "couldn't" in resp.message.lower()
