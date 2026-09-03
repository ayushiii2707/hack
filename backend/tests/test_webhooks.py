import json

import pytest

from app.core.constants import OrderStatus
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.payment_service import PaymentService
from tests.factories import FAKE_WEBHOOK_SECRET, make_product, sign


@pytest.fixture()
def order(db_session, shop):
    p = make_product(db_session, price=249900, stock=10)
    CartService(db_session).add_item(shop.session.cart.id, p.id, 1)
    return CheckoutService(db_session).confirm_checkout(shop.session.id)


def _svc(db_session, fake_rzp):
    return PaymentService(db_session, client=fake_rzp)


def _captured_event(rzp_order_id, pid, amount):
    return {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": pid, "order_id": rzp_order_id, "status": "captured", "amount": amount,
        }}},
    }


def test_webhook_marks_paid_after_reconciliation(db_session, order, fake_rzp):
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    r = s.handle_webhook_event(
        _captured_event(init["razorpay_order_id"], pid, order.amount), event_id="evt_1"
    )
    assert r["order_status"] == "PAID"
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID


def test_webhook_amount_mismatch_rejected(db_session, order, fake_rzp):
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    r = s.handle_webhook_event(
        _captured_event(init["razorpay_order_id"], pid, order.amount - 500), event_id="evt_x"
    )
    assert r.get("rejected") is True
    db_session.refresh(order)
    assert order.status != OrderStatus.PAID


def test_duplicate_event_id_is_ignored(db_session, order, fake_rzp):
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    ev = _captured_event(init["razorpay_order_id"], pid, order.amount)
    r1 = s.handle_webhook_event(ev, event_id="evt_dup")
    r2 = s.handle_webhook_event(ev, event_id="evt_dup")
    assert r1["order_status"] == "PAID"
    assert r2.get("idempotent") is True
    assert len(s.list_attempts(order.id)) == 1


def test_late_failure_cannot_unpay(db_session, order, fake_rzp):
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    s.handle_webhook_event(_captured_event(init["razorpay_order_id"], pid, order.amount), event_id="e1")
    r = s.handle_webhook_event({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": pid, "order_id": init["razorpay_order_id"], "status": "failed",
            "error_description": "late failure",
        }}},
    }, event_id="e2")
    assert r.get("idempotent") is True
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID


def test_webhook_on_cancelled_order_never_resurrects_it(db_session, shop, fake_rzp):
    from app.services.checkout_service import CheckoutService

    p = make_product(db_session, price=100000, stock=10)
    CartService(db_session).add_item(shop.session.cart.id, p.id, 1)
    o = CheckoutService(db_session).confirm_checkout(shop.session.id)
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(o)
    CheckoutService(db_session).cancel_checkout(shop.session.id)

    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    r = s.handle_webhook_event(
        _captured_event(init["razorpay_order_id"], pid, o.amount), event_id="evt_cxl"
    )
    assert r.get("needs_reconciliation") is True
    db_session.refresh(o)
    assert o.status == OrderStatus.CANCELLED  # not PAID


def test_order_paid_event_payload_shape_handled(db_session, order, fake_rzp):
    s = _svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, _ = fake_rzp.simulate_success(init["razorpay_order_id"])
    ev = {
        "event": "order.paid",
        "payload": {
            "order": {"entity": {"id": init["razorpay_order_id"], "amount": order.amount}},
            "payment": {"entity": {"id": pid, "order_id": init["razorpay_order_id"], "status": "captured", "amount": order.amount}},
        },
    }
    r = s.handle_webhook_event(ev, event_id="evt_op")
    assert r["order_status"] == "PAID"


# ---- endpoint-level ----
def test_webhook_endpoint_rejects_bad_signature(client, order):
    body = json.dumps({"event": "payment.captured", "payload": {}})
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": "bad", "content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["status"] == "invalid_signature"


def test_webhook_endpoint_fails_closed_without_secret(client, order, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "razorpay_webhook_secret", "")
    body = json.dumps({"event": "payment.captured", "payload": {}})
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": sign(body, "whatever"),
                             "content-type": "application/json"})
    assert r.status_code == 503
    assert r.json()["status"] == "webhook_not_configured"


def test_webhook_endpoint_valid_signature_processed(client, db_session, order, fake_rzp):
    init = PaymentService(db_session, client=fake_rzp).ensure_payment_order(order)
    body = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_WHF", "order_id": init["razorpay_order_id"],
            "status": "failed", "error_description": "declined",
        }}},
    })
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": sign(body, FAKE_WEBHOOK_SECRET),
                             "X-Razorpay-Event-Id": "evt_api_1",
                             "content-type": "application/json"})
    assert r.json()["status"] == "ok"
    db_session.refresh(order)
    assert order.status == OrderStatus.PAYMENT_FAILED
