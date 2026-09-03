"""End-to-end business flow through the HTTP API (fake gateway).

Create session -> search -> add -> cart -> total -> upsell -> decline ->
second upsell blocked -> modify cart -> still blocked -> review -> confirm
(stock reserved) -> pay attempt #1 FAILS -> order NOT paid -> retry ->
verified success -> order PAID -> session COMPLETED -> audit trail intact.
"""
from __future__ import annotations

from app.core.constants import AuditAction
from tests.factories import make_product


def test_full_purchase_flow_with_failure_and_recovery(api, db_session, fake_rzp):
    shoes = make_product(db_session, external_id="sh", name="Velocity Running Shoes",
                         category="mens-shoes", brand="Velocity", price=280000, stock=10,
                         tags=["running", "shoes"])
    make_product(db_session, external_id="sk", name="Running Socks", category="mens-shoes",
                 brand="Velocity", price=15000, stock=50, tags=["running", "socks"])
    other = make_product(db_session, external_id="wb", name="Water Bottle",
                         category="sports-accessories", price=12000, stock=10, tags=["hydration"])

    # 1-3. discover via the conversational agent + add + view cart
    chat = api.post("/agent/chat", json={"message": "show me running shoes under 3000"}).json()
    shown = next(a for a in chat["actions"] if a["type"] == "SHOW_PRODUCTS")
    assert shoes.id in shown["payload"]["product_ids"]
    cart = api.post("/cart/items", json={"product_id": shoes.id, "quantity": 1}).json()
    assert cart["totals"]["total"] == 280000

    # 4-5. review + upsell
    review = api.post("/checkout/review").json()
    assert review["upsell_available"] is True
    up = api.post("/upsell").json()
    assert up["available"] is True and up["product"]["price"] <= up["price_cap"]

    # 6-8. decline, second upsell blocked, cart change, still blocked
    api.post("/upsell/decline")
    assert api.post("/upsell").json()["available"] is False
    api.post("/cart/items", json={"product_id": other.id, "quantity": 1})
    assert api.post("/upsell").json()["available"] is False

    # 9. confirm -> order + stock reserved
    confirmed = api.post("/checkout/confirm").json()
    order_amount = confirmed["order"]["amount"]
    assert order_amount == 292000
    db_session.expire_all()
    assert db_session.get(type(shoes), shoes.id).stock == 9

    init = api.post("/payments/order").json()
    assert init["amount"] == order_amount

    # 10-11. attempt #1 fails; order NOT paid
    fail = api.post("/payments/failed", json={"reason": "card declined"}).json()
    assert fail["success"] is False
    assert api.get("/checkout/summary").json()  # session still usable
    db_session.expire_all()

    # 12-13. retry -> verified success
    init2 = api.post("/payments/order").json()  # same razorpay order
    assert init2["razorpay_order_id"] == init["razorpay_order_id"]
    pid, sig = fake_rzp.simulate_success(init2["razorpay_order_id"])
    verified = api.post("/payments/verify", json={
        "razorpay_order_id": init2["razorpay_order_id"],
        "razorpay_payment_id": pid, "razorpay_signature": sig,
    }).json()
    assert verified["success"] is True and verified["order_status"] == "PAID"

    me = api.get("/sessions/me").json()
    assert me["state"] == "COMPLETED"

    attempts = api.get("/payments/attempts").json()
    assert [a["status"] for a in attempts] == ["FAILED", "CAPTURED"]

    # audit trail
    actions = {e["action"] for e in api.get("/audit").json()["items"]}
    for expected in (
        AuditAction.SESSION_CREATED.value, AuditAction.PRODUCT_SEARCHED.value,
        AuditAction.ITEM_ADDED.value, AuditAction.UPSELL_SHOWN.value,
        AuditAction.UPSELL_DECLINED.value, AuditAction.CHECKOUT_STARTED.value,
        AuditAction.PAYMENT_ATTEMPTED.value, AuditAction.PAYMENT_FAILED.value,
        AuditAction.PAYMENT_SUCCESS.value,
    ):
        assert expected in actions, expected
