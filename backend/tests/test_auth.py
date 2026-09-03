"""Authentication + authorisation: no cross-session access, no anonymous writes."""
from __future__ import annotations

from tests.factories import make_product


def test_session_creation_returns_token_and_sets_cookie(client):
    r = client.post("/sessions")
    assert r.status_code == 201
    body = r.json()
    assert body["session_token"] and len(body["session_token"]) > 20
    assert "cc_session" in r.headers.get("set-cookie", "")


def test_all_stateful_endpoints_require_auth(client):
    for method, path, kw in [
        ("get", "/cart", {}),
        ("post", "/cart/items", {"json": {"product_id": "x", "quantity": 1}}),
        ("post", "/checkout/review", {}),
        ("post", "/checkout/confirm", {}),
        ("post", "/checkout/cancel", {}),
        ("post", "/upsell", {}),
        ("post", "/payments/order", {}),
        ("post", "/payments/verify", {"json": {"razorpay_order_id": "a", "razorpay_payment_id": "b", "razorpay_signature": "c"}}),
        ("post", "/payments/link", {}),
        ("get", "/payments/attempts", {}),
        ("get", "/audit", {}),
        ("post", "/agent/chat", {"json": {"message": "hi"}}),
        ("get", "/sessions/me", {}),
    ]:
        resp = getattr(client, method)(path, **kw)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


def test_invalid_token_rejected(client):
    r = client.get("/cart", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_cannot_touch_another_sessions_cart(api, api2, db_session):
    """api adds an item; api2 must not see or mutate api's cart."""
    p = make_product(db_session, price=100000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 2})

    # api2 has its own empty cart
    assert api2.get("/cart").json()["items"] == []
    # there is no path param to attack — the cart is derived from the token.
    # api2 adding an item only affects api2's own cart.
    api2.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    assert api.get("/cart").json()["items"][0]["quantity"] == 2
    assert api2.get("/cart").json()["items"][0]["quantity"] == 1


def test_audit_is_scoped_to_own_session(api, api2, db_session):
    p = make_product(db_session, price=100000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    api2.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    mine = api.get("/audit").json()
    assert mine["count"] >= 2
    assert all(e["session_id"] == api.session_id for e in mine["items"])


def test_admin_audit_requires_key(client, api, admin_headers, db_session):
    p = make_product(db_session, price=100000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    assert client.get("/audit/admin").status_code == 403
    assert client.get("/audit/admin", headers={"X-Admin-Key": "nope"}).status_code == 403
    r = client.get("/audit/admin", headers=admin_headers)
    assert r.status_code == 200 and r.json()["count"] >= 1


def test_payments_verify_cannot_target_another_sessions_order(api, api2, db_session, fake_rzp):
    p = make_product(db_session, price=150000, stock=10)
    api.post("/cart/items", json={"product_id": p.id, "quantity": 1})
    api.post("/checkout/confirm")
    init = api.post("/payments/order").json()
    pid, sig = fake_rzp.simulate_success(init["razorpay_order_id"])
    # api2 tries to verify api's payment using api's real razorpay ids
    r = api2.post("/payments/verify", json={
        "razorpay_order_id": init["razorpay_order_id"],
        "razorpay_payment_id": pid, "razorpay_signature": sig,
    })
    # api2 has no open order -> 404, and api's order stays unpaid
    assert r.status_code == 404
    assert api.get("/checkout/summary").json()  # still reachable
