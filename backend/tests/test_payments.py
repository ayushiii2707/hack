import json

import pytest

from app.core.constants import AuditAction, OrderStatus, PaymentStatus, SessionState
from app.core.exceptions import ConflictError, PaymentVerificationError
from app.models.audit_log import AuditLog
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.payment_service import PaymentService
from app.services.session_service import SessionService
from tests.factories import make_product, sign


@pytest.fixture()
def order(db_session, shop):
    p = make_product(db_session, price=249900, stock=10)
    CartService(db_session).add_item(shop.session.cart.id, p.id, 1)
    return CheckoutService(db_session).confirm_checkout(shop.session.id)


def svc(db_session, fake_rzp) -> PaymentService:
    return PaymentService(db_session, client=fake_rzp)


def _init(db_session, fake_rzp, order):
    return svc(db_session, fake_rzp).ensure_payment_order(order)


def test_razorpay_order_created_with_amount_in_paise(db_session, order, fake_rzp):
    init = _init(db_session, fake_rzp, order)
    assert init["amount"] == 249900
    assert init["razorpay_order_id"].startswith("order_FAKE")
    assert "secret" not in json.dumps(init).lower()
    db_session.refresh(order)
    assert order.status == OrderStatus.PAYMENT_PENDING


def test_verify_success_marks_paid_and_completes_session(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    result = s.verify_payment(
        order=order, razorpay_order_id=init["razorpay_order_id"],
        razorpay_payment_id=pid, razorpay_signature=sig,
    )
    assert result.success is True
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID
    assert order.open_cart_key is None
    session = SessionService(db_session).get_session(order.session_id)
    assert session.state == SessionState.COMPLETED


def test_forged_signature_does_not_mark_paid_or_fail_order(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    with pytest.raises(PaymentVerificationError):
        s.verify_payment(
            order=order, razorpay_order_id=init["razorpay_order_id"],
            razorpay_payment_id="pay_FORGED", razorpay_signature="deadbeef",
        )
    db_session.refresh(order)
    assert order.status != OrderStatus.PAID
    # a forged verify must NOT flip the order to FAILED (that would be a DoS)
    assert order.status == OrderStatus.PAYMENT_PENDING
    actions = {a.action for a in db_session.query(AuditLog).all()}
    assert AuditAction.PAYMENT_VERIFICATION_FAILED in actions


def test_valid_signature_but_amount_mismatch_is_rejected(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, sig = fake_rzp.simulate_amount_mismatch(init["razorpay_order_id"])
    with pytest.raises(PaymentVerificationError):
        s.verify_payment(
            order=order, razorpay_order_id=init["razorpay_order_id"],
            razorpay_payment_id=pid, razorpay_signature=sig,
        )
    db_session.refresh(order)
    assert order.status != OrderStatus.PAID


def test_valid_signature_but_unsettled_status_is_rejected(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, sig = fake_rzp.simulate_unsettled(init["razorpay_order_id"])
    with pytest.raises(PaymentVerificationError):
        s.verify_payment(
            order=order, razorpay_order_id=init["razorpay_order_id"],
            razorpay_payment_id=pid, razorpay_signature=sig,
        )
    db_session.refresh(order)
    assert order.status != OrderStatus.PAID


def test_failed_attempt_persisted_then_retry_succeeds(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    s.record_client_failure(order=order, reason="card declined")
    assert [a.status for a in s.list_attempts(order.id)] == [PaymentStatus.FAILED]

    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    s.verify_payment(order=order, razorpay_order_id=init["razorpay_order_id"],
                     razorpay_payment_id=pid, razorpay_signature=sig)
    attempts = s.list_attempts(order.id)
    assert len(attempts) == 2
    assert attempts[0].status == PaymentStatus.FAILED
    assert attempts[1].status == PaymentStatus.CAPTURED
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID


def test_repeated_client_failure_reports_are_idempotent(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    s.ensure_payment_order(order)
    for i in range(6):
        s.record_client_failure(order=order, reason=f"retry {i}")
        db_session.expire_all()
        order = s._get_order(order.id)
    assert len(s.list_attempts(order.id)) == 1  # not 6


def test_terminal_attempt_is_immutable(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    s.verify_payment(order=order, razorpay_order_id=init["razorpay_order_id"],
                     razorpay_payment_id=pid, razorpay_signature=sig)
    captured = s.payments.get_captured(order.id)
    with pytest.raises(ValueError):
        s.payments.finalize(captured, status=PaymentStatus.FAILED)


def test_payment_link_fallback_no_url_in_audit_reason(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    s.ensure_payment_order(order)
    data = s.create_payment_link(order)
    assert data["short_url"].startswith("https://rzp.io/i/")
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.PAYMENT_LINK_CREATED
    ).one()
    assert "http" not in audit.reason  # scrubbed
    assert "short_url" not in json.dumps(json.loads(audit.meta))
    again = s.create_payment_link(order)
    assert again["reused"] is True


def test_wrong_razorpay_order_id_is_rejected(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    s.ensure_payment_order(order)
    with pytest.raises(PaymentVerificationError):
        s.verify_payment(order=order, razorpay_order_id="order_SOMEONE_ELSE",
                         razorpay_payment_id="pay_x", razorpay_signature="whatever")


def test_verify_is_idempotent(db_session, order, fake_rzp):
    s = svc(db_session, fake_rzp)
    init = s.ensure_payment_order(order)
    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    kw = dict(order=order, razorpay_order_id=init["razorpay_order_id"],
              razorpay_payment_id=pid, razorpay_signature=sig)
    r1 = s.verify_payment(**kw)
    r2 = s.verify_payment(**kw)
    assert r1.success and r2.success
    assert len(s.list_attempts(order.id)) == 1


# ---- API level ----
def test_payments_api_verify_endpoint(api, db_session, fake_rzp):
    p = make_product(db_session, price=150000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    api.post("/checkout/confirm")
    init = api.post("/payments/order").json()
    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    r = api.post("/payments/verify", json={
        "razorpay_order_id": init["razorpay_order_id"],
        "razorpay_payment_id": pid, "razorpay_signature": sig,
    })
    assert r.status_code == 200 and r.json()["success"] is True


def test_payments_api_verify_rejects_forged(api, db_session, fake_rzp):
    p = make_product(db_session, price=150000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    api.post("/checkout/confirm")
    init = api.post("/payments/order").json()
    r = api.post("/payments/verify", json={
        "razorpay_order_id": init["razorpay_order_id"],
        "razorpay_payment_id": "pay_FORGE", "razorpay_signature": "0" * 64,
    })
    assert r.status_code == 200 and r.json()["success"] is False


def test_payments_api_requires_auth(client):
    assert client.post("/payments/order").status_code == 401
    assert client.post("/payments/verify", json={
        "razorpay_order_id": "x", "razorpay_payment_id": "y", "razorpay_signature": "z"}
    ).status_code == 401


def test_simulate_failure_requires_demo_flag(api, db_session, fake_rzp, monkeypatch):
    p = make_product(db_session, price=150000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    api.post("/checkout/confirm")
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_demo_endpoints", False)
    assert api.post("/payments/simulate-failure").status_code == 403
    monkeypatch.setattr(settings, "enable_demo_endpoints", True)
    assert api.post("/payments/simulate-failure").json()["success"] is False
