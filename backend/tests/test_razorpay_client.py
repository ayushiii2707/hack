"""RazorpayClient must honour ``settings.razorpay_base_url`` so a staging
sandbox (or, in QC, a local stub server that speaks the same shape) can be
targeted without any code change. It must never silently fall back to the
real Razorpay API when an override is configured.
"""
from __future__ import annotations

from app.core.config import settings
from app.integrations.razorpay.client import RazorpayClient


def test_client_uses_configured_base_url_by_default():
    client = RazorpayClient(key_id="rzp_test_x", key_secret="secret")
    # Must be the bare host: the SDK's resources already add "/v1/<resource>".
    assert client._sdk.base_url == "https://api.razorpay.com"


def test_client_honours_a_base_url_override(monkeypatch):
    monkeypatch.setattr(settings, "razorpay_base_url", "http://127.0.0.1:9999")
    client = RazorpayClient(key_id="rzp_test_x", key_secret="secret")
    assert client._sdk.base_url == "http://127.0.0.1:9999"


def test_order_create_hits_v1_orders_exactly_once_not_doubled(monkeypatch):
    """Regression for a real bug this QC pass caught: the SDK's resource
    classes already prepend "/v1/orders" to whatever base_url the client is
    given, so a base_url ending in "/v1" produces ".../v1/v1/orders" and every
    gateway call 404s. Assert the exact request URL, not just the base_url
    field, so this class of bug can't reappear silently.
    """
    monkeypatch.setattr(settings, "razorpay_base_url", "http://127.0.0.1:9999")
    client = RazorpayClient(key_id="rzp_test_x", key_secret="secret")

    captured = {}

    def fake_request(self, method, url, **kwargs):
        captured["method"], captured["url"] = method, url

        class Resp:
            status_code = 200

            def json(self):
                return {"id": "order_x", "amount": 100, "currency": "INR", "status": "created"}

        return Resp()

    monkeypatch.setattr(type(client._sdk.session), "request", fake_request, raising=False)
    client.create_order(amount=100, currency="INR", receipt="r1")
    assert captured["url"] == "http://127.0.0.1:9999/v1/orders", captured["url"]
