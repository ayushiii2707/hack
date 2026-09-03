"""Test helpers: fake catalog + Razorpay providers, model builders, auth."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from app.core.exceptions import PaymentVerificationError
from app.integrations.catalog.base import CatalogProvider, RawProduct
from app.models.product import Product

FAKE_KEY_ID = "rzp_test_dummy"
FAKE_KEY_SECRET = "dummysecret"
FAKE_WEBHOOK_SECRET = "whsec_dummy"


def sign(msg: str, secret: str = FAKE_KEY_SECRET) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- catalog
class FakeCatalogProvider(CatalogProvider):
    source = "fake"

    def __init__(self, items: list[dict]):
        self._items = items

    def fetch_products(self, *, limit: int = 100, skip: int = 0) -> list[RawProduct]:
        page = self._items[skip : skip + limit]
        return [RawProduct(source=self.source, external_id=str(i["id"]), payload=i) for i in page]

    def fetch_product(self, external_id: str) -> RawProduct | None:
        for i in self._items:
            if str(i["id"]) == str(external_id):
                return RawProduct(source=self.source, external_id=str(i["id"]), payload=i)
        return None

    def search_products(self, query: str, *, limit: int = 20) -> list[RawProduct]:
        q = query.lower()
        hits = [i for i in self._items if q in i.get("title", "").lower()]
        return [RawProduct(source=self.source, external_id=str(i["id"]), payload=i) for i in hits[:limit]]


def sample_catalog() -> list[dict]:
    return [
        {
            "id": 101, "title": "Velocity Running Shoes", "description": "Lightweight road running shoes",
            "category": "mens-shoes", "price": 30.11, "stock": 25, "brand": "Velocity",
            "sku": "RUN-101", "tags": ["running", "shoes"],
            "images": ["http://img/101.jpg"], "thumbnail": "http://img/101t.jpg",
        },
        {
            "id": 102, "title": "Running Socks 3-pack", "description": "Cushioned athletic socks",
            "category": "mens-shoes", "price": 4.80, "stock": 200, "brand": "Velocity",
            "sku": "SOCK-102", "tags": ["running", "socks"], "images": [], "thumbnail": "",
        },
        {
            "id": 103, "title": "Steel Water Bottle", "description": "750ml insulated bottle",
            "category": "sports-accessories", "price": 7.20, "stock": 0, "brand": "HydroMax",
            "sku": "BTL-103", "tags": ["hydration"], "images": ["http://img/103.jpg"],
        },
        {
            "id": 104, "title": "Broken Product", "description": "no price", "category": "misc",
            "price": None, "stock": 5, "tags": [],
        },
    ]


# ---------------------------------------------------------------- razorpay
class FakeRazorpayClient:
    """Mirrors app.integrations.razorpay.client.RazorpayClient with real HMAC.

    Tracks the orders it creates so ``fetch_payment`` / ``simulate_*`` can
    return gateway data that is consistent with the internal order amount.
    """

    def __init__(self):
        self.key_id = FAKE_KEY_ID
        self.key_secret = FAKE_KEY_SECRET
        self._seq = 0
        self.orders: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.payment_links: list[dict] = []

    # -- orders --
    def create_order(self, *, amount, currency, receipt, notes=None):
        self._seq += 1
        oid = f"order_FAKE{self._seq:08d}"
        raw = {"id": oid, "amount": int(amount), "currency": currency, "status": "created",
               "receipt": receipt, "notes": notes or {}}
        self.orders[oid] = raw
        return raw

    def find_order_by_receipt(self, receipt):
        for o in self.orders.values():
            if o.get("receipt") == receipt:
                return o
        return None

    def fetch_order(self, razorpay_order_id):
        return self.orders.get(razorpay_order_id, {"id": razorpay_order_id, "status": "created"})

    # -- payments --
    def fetch_payment(self, razorpay_payment_id):
        return self.payments.get(
            razorpay_payment_id,
            {"id": razorpay_payment_id, "status": "failed", "amount": None, "currency": None},
        )

    def _register_payment(self, *, rzp_order_id, status, amount, currency):
        self._seq += 1
        pid = f"pay_FAKE{self._seq:08d}"
        self.payments[pid] = {
            "id": pid, "order_id": rzp_order_id, "status": status,
            "amount": amount, "currency": currency, "method": "card",
        }
        return pid

    def simulate_success(self, rzp_order_id: str) -> tuple[str, str]:
        o = self.orders[rzp_order_id]
        pid = self._register_payment(
            rzp_order_id=rzp_order_id, status="captured", amount=o["amount"], currency=o["currency"]
        )
        return pid, sign(f"{rzp_order_id}|{pid}")

    def simulate_amount_mismatch(self, rzp_order_id: str) -> tuple[str, str]:
        o = self.orders[rzp_order_id]
        pid = self._register_payment(
            rzp_order_id=rzp_order_id, status="captured", amount=o["amount"] - 100, currency=o["currency"]
        )
        return pid, sign(f"{rzp_order_id}|{pid}")  # valid signature, wrong amount

    def simulate_unsettled(self, rzp_order_id: str) -> tuple[str, str]:
        o = self.orders[rzp_order_id]
        pid = self._register_payment(
            rzp_order_id=rzp_order_id, status="failed", amount=o["amount"], currency=o["currency"]
        )
        return pid, sign(f"{rzp_order_id}|{pid}")

    # -- payment links --
    def create_payment_link(self, payload):
        pid = f"plink_FAKE{len(self.payment_links) + 1:04d}"
        raw = {"id": pid, "short_url": f"https://rzp.io/i/{pid}", "status": "created",
               "reference_id": payload.get("reference_id"), "amount": payload.get("amount")}
        self.payment_links.append(raw)
        return raw

    # -- signatures --
    def verify_payment_signature(self, *, razorpay_order_id, razorpay_payment_id, razorpay_signature):
        expected = sign(f"{razorpay_order_id}|{razorpay_payment_id}")
        if not hmac.compare_digest(expected, razorpay_signature):
            raise PaymentVerificationError("Payment signature verification failed.")

    def verify_webhook_signature(self, *, body, signature):
        expected = sign(body, FAKE_WEBHOOK_SECRET)
        if not hmac.compare_digest(expected, signature):
            raise PaymentVerificationError("Webhook signature verification failed.")


# ---------------------------------------------------------------- models
def make_product(db, **overrides) -> Product:
    defaults = dict(
        external_id=f"e{secrets.token_hex(4)}", source="fake", name="Test Product",
        description="desc", category="test", brand="TestBrand", price=100000, currency="INR",
        image_url="", product_url="", stock=10, sku="SKU1", tags=json.dumps(["test"]),
        active=True,
    )
    defaults.update(overrides)
    if isinstance(defaults.get("tags"), list):
        defaults["tags"] = json.dumps(defaults["tags"])
    p = Product(**defaults)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
