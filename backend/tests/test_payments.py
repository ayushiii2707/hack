import json

import pytest

from app.core.constants import OrderStatus, PaymentStatus, SessionState
from app.core.exceptions import PaymentVerificationError
from app.models.audit_log import AuditLog
from app.core.constants import AuditAction
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.payment_service import PaymentService
from app.services.session_service import SessionService
from tests.factories import FAKE_WEBHOOK_SECRET, make_product, sign


@pytest.fixture()
def order(db_session):
    session = SessionService(db_session).create_session()
    p = make_product(db_session, price=249900, stock=10)
    CartService(db_session).add_item(session.cart.id, p.id, 1)
    return CheckoutService(db_session).confirm_checkout(session.id)


def _svc(db_session, fake_rzp):
    return PaymentService(db_session, client=fake_rzp)


def test_razorpay_order_created_with_amount_in_paise(db_session, order, fake_rzp):
    init = _svc(db_session, fake_rzp).ensure_payment_order(order)
    assert init["amount"] == 249900
    assert init["razorpay_order_id"].startswith("order_FAKE")
    assert "key_secret" not in init and "secret" not in json.dumps(init).lower()
    db_session.refresh(order)
    assert order.status == OrderStatus.PAYMENT_PENDING


def test_verify_success_marks_paid_and_completes_session(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    init = svc.ensure_payment_order(order)
    rzp_order_id = init["razorpay_order_id"]
    pay_id = "pay_FAKE0001"
    good_sig = sign(f"{rzp_order_id}|{pay_id}")
    result = svc.verify_payment(
        order_id=order.id,
        razorpay_order_id=rzp_order_id,
        razorpay_payment_id=pay_id,
        razorpay_signature=good_sig,
    )
    assert result.success is True
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID
    session = SessionService(db_session).get_session(order.session_id)
    assert session.state == SessionState.COMPLETED


def test_fake_payment_success_without_valid_signature_is_rejected(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    init = svc.ensure_payment_order(order)
    with pytest.raises(PaymentVerificationError):
        svc.verify_payment(
            order_id=order.id,
            razorpay_order_id=init["razorpay_order_id"],
            razorpay_payment_id="pay_FORGED",
            razorpay_signature="deadbeef",
        )
    db_session.refresh(order)
    assert order.status == OrderStatus.PAYMENT_FAILED
    assert order.status != OrderStatus.PAID


def test_failed_attempt_is_persisted_then_retry_succeeds(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    init = svc.ensure_payment_order(order)
    rzp_order_id = init["razorpay_order_id"]

    # attempt #1 fails at the gateway
    svc.mark_payment_failed(order_id=order.id, reason="card declined")
    attempts = svc.list_attempts(order.id)
    assert [a.status for a in attempts] == [PaymentStatus.FAILED]

    # attempt #2 succeeds
    pay_id = "pay_RETRY_OK"
    svc.verify_payment(
        order_id=order.id,
        razorpay_order_id=rzp_order_id,
        razorpay_payment_id=pay_id,
        razorpay_signature=sign(f"{rzp_order_id}|{pay_id}"),
    )
    attempts = svc.list_attempts(order.id)
    assert len(attempts) == 2
    assert attempts[0].status == PaymentStatus.FAILED
    assert attempts[1].status == PaymentStatus.CAPTURED
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID


def test_payment_link_fallback(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    svc.ensure_payment_order(order)
    data = svc.create_payment_link(order.id)
    assert data["short_url"].startswith("https://rzp.io/i/plink_FAKE")
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == AuditAction.PAYMENT_LINK_CREATED
    ).all()
    assert len(audit) == 1
    # idempotent-ish: second call reuses the link
    again = svc.create_payment_link(order.id)
    assert again["reused"] is True


def test_wrong_razorpay_order_id_is_rejected(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    svc.ensure_payment_order(order)
    with pytest.raises(PaymentVerificationError):
        svc.verify_payment(
            order_id=order.id,
            razorpay_order_id="order_SOMEONE_ELSE",
            razorpay_payment_id="pay_x",
            razorpay_signature="whatever",
        )


def test_duplicate_webhook_does_not_corrupt_state(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    init = svc.ensure_payment_order(order)
    event = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_WH1", "order_id": init["razorpay_order_id"], "status": "captured",
        }}},
    }
    r1 = svc.handle_webhook_event(event)
    r2 = svc.handle_webhook_event(event)
    assert r1["order_status"] == "PAID"
    assert r2.get("idempotent") is True
    assert len(svc.list_attempts(order.id)) == 1
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID


def test_webhook_invalid_signature_rejected(client, db_session, order, fake_rzp):
    body = json.dumps({"event": "payment.captured", "payload": {}})
    r = client.post(
        "/webhooks/razorpay", content=body,
        headers={"X-Razorpay-Signature": "bad", "content-type": "application/json"},
    )
    assert r.json()["status"] == "invalid_signature"


def test_webhook_valid_signature_processed(client, db_session, order, fake_rzp):
    init = PaymentService(db_session, client=fake_rzp).ensure_payment_order(order)
    body = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_WHF", "order_id": init["razorpay_order_id"],
            "status": "failed", "error_description": "declined",
        }}},
    })
    r = client.post(
        "/webhooks/razorpay", content=body,
        headers={"X-Razorpay-Signature": sign(body, FAKE_WEBHOOK_SECRET),
                 "content-type": "application/json"},
    )
    assert r.json()["status"] == "ok"
    db_session.refresh(order)
    assert order.status == OrderStatus.PAYMENT_FAILED


def test_verify_is_idempotent(db_session, order, fake_rzp):
    svc = _svc(db_session, fake_rzp)
    init = svc.ensure_payment_order(order)
    rzp_order_id = init["razorpay_order_id"]
    pay_id = "pay_IDEM"
    sig = sign(f"{rzp_order_id}|{pay_id}")
    kw = dict(order_id=order.id, razorpay_order_id=rzp_order_id,
              razorpay_payment_id=pay_id, razorpay_signature=sig)
    r1 = svc.verify_payment(**kw)
    r2 = svc.verify_payment(**kw)
    assert r1.success and r2.success
    assert len(svc.list_attempts(order.id)) == 1


def test_payments_api_verify_endpoint(client, db_session, order, fake_rzp):
    init = client.post("/payments/order", json={"order_id": order.id}).json()
    rzp_order_id = init["razorpay_order_id"]
    pay_id = "pay_API_OK"
    r = client.post("/payments/verify", json={
        "order_id": order.id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": pay_id,
        "razorpay_signature": sign(f"{rzp_order_id}|{pay_id}"),
    })
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_payments_api_verify_rejects_forged(client, db_session, order, fake_rzp):
    init = client.post("/payments/order", json={"order_id": order.id}).json()
    r = client.post("/payments/verify", json={
        "order_id": order.id,
        "razorpay_order_id": init["razorpay_order_id"],
        "razorpay_payment_id": "pay_FORGE",
        "razorpay_signature": "0" * 64,
    })
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert client.get(f"/checkout/{order.session_id}/summary")  # sanity
