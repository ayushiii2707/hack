"""Hard-boundary tests: malicious / invalid agent tool requests are blocked."""
from __future__ import annotations

import json

import pytest

from app.agent.policies import PolicyEngine
from app.agent.tools import ToolContext, build_tools
from app.core.constants import AuditAction
from app.models.audit_log import AuditLog
from app.services.cart_service import CartService
from app.services.session_service import SessionService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def session_obj(db_session):
    return SessionService(db_session).create_session()


def _tools(db_session, session_obj):
    ctx = ToolContext(db=db_session, session_id=session_obj.id, cart_id=session_obj.cart.id)
    return {t.name: t for t in build_tools(ctx)}, ctx


def test_quantity_abuse_blocked_and_audited(db_session, session_obj):
    p = make_product(db_session, price=100000, stock=100000)
    tools, _ = _tools(db_session, session_obj)
    out = json.loads(tools["add_to_cart"].invoke({"product_id": p.id, "quantity": 5}))
    assert out["ok"] is True
    # now push over the cap with an incremental add
    out2 = json.loads(tools["add_to_cart"].invoke({"product_id": p.id, "quantity": 5}))
    assert out2["ok"] is False
    assert out2["error"]["code"] == "POLICY_BLOCKED"
    blocked = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.POLICY_BLOCKED
    ).count()
    assert blocked >= 1


def test_no_payment_capability_exists(db_session, session_obj):
    tools, _ = _tools(db_session, session_obj)
    assert "start_checkout" in tools
    assert not any("pay" in n for n in tools)
    # policy explicitly denies payment creation/retry
    pe = PolicyEngine(db_session, session_obj.id)
    assert pe.can_create_payment().allowed is False
    assert pe.can_retry_payment().allowed is False


def test_second_upsell_via_tool_blocked(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    tools, _ = _tools(db_session, session_obj)
    first = json.loads(tools["request_upsell"].invoke({}))
    assert first["ok"] is True
    second = json.loads(tools["request_upsell"].invoke({}))
    assert second["ok"] is False and second["error"]["code"] == "POLICY_BLOCKED"


def test_declined_upsell_then_tool_request_blocked(db_session, session_obj):
    anchor = make_product(db_session, external_id="a", name="Shoes", category="mens-shoes",
                          price=280000, stock=10, tags=["running"])
    make_product(db_session, external_id="b", name="Socks", category="mens-shoes",
                 price=15000, stock=10, tags=["running", "socks"])
    CartService(db_session).add_item(session_obj.cart.id, anchor.id, 1)
    UpsellService(db_session).generate_recommendation(session_obj.id)
    UpsellService(db_session).decline(session_obj.id)
    tools, _ = _tools(db_session, session_obj)
    out = json.loads(tools["request_upsell"].invoke({}))
    assert out["ok"] is False


def test_fake_payment_success_without_verification_not_marked_paid(db_session, session_obj, fake_rzp):
    from app.services.checkout_service import CheckoutService
    from app.services.payment_service import PaymentService

    p = make_product(db_session, price=150000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    order = CheckoutService(db_session).confirm_checkout(session_obj.id)
    svc = PaymentService(db_session, client=fake_rzp)
    init = svc.ensure_payment_order(order)
    from app.core.exceptions import PaymentVerificationError

    with pytest.raises(PaymentVerificationError):
        svc.verify_payment(
            order_id=order.id,
            razorpay_order_id=init["razorpay_order_id"],
            razorpay_payment_id="pay_CLIENT_SAYS_OK",
            razorpay_signature="not-a-real-signature",
        )
    db_session.refresh(order)
    assert order.status.value != "PAID"


def test_cart_locked_after_checkout_confirm(db_session, session_obj, fake_rzp):
    from app.services.checkout_service import CheckoutService

    p = make_product(db_session, price=150000, stock=10)
    CartService(db_session).add_item(session_obj.cart.id, p.id, 1)
    CheckoutService(db_session).confirm_checkout(session_obj.id)
    tools, _ = _tools(db_session, session_obj)
    out = json.loads(tools["add_to_cart"].invoke({"product_id": p.id, "quantity": 1}))
    assert out["ok"] is False and out["error"]["code"] == "POLICY_BLOCKED"
