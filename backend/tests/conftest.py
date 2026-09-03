"""Shared test fixtures: isolated in-memory DB, fake Razorpay, auth helpers."""
from __future__ import annotations

import os

# Pin config for deterministic tests, overriding any local .env.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_TOKEN_SECRET"] = "test-pepper-0123456789012345678901234567890123"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["ENABLE_DEMO_ENDPOINTS"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["CATALOG_PRICE_MULTIPLIER"] = "35"
os.environ["MAX_ITEM_QUANTITY"] = "5"
os.environ["UPSELL_PRICE_CAP_PERCENT"] = "20"
os.environ["SHIPPING_FEE"] = "500"
os.environ["FREE_SHIPPING_THRESHOLD"] = "200000"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dummy"
os.environ["RAZORPAY_KEY_SECRET"] = "dummysecret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_dummy"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.database.database import get_db
from app.main import app as fastapi_app
from app.models.base import Base


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def _SessionLocal(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db_session(_SessionLocal):
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def fake_rzp(monkeypatch):
    """Patch every get_razorpay_client() seam with one shared fake client."""
    from tests.factories import FakeRazorpayClient

    client = FakeRazorpayClient()
    for mod in ("app.services.payment_service", "app.api.webhooks"):
        monkeypatch.setattr(f"{mod}.get_razorpay_client", lambda: client, raising=True)
    return client


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.core.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def client(_SessionLocal):
    def _override_get_db():
        db = _SessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


class AuthClient:
    """A TestClient wrapper that carries a session bearer token."""

    def __init__(self, tc: TestClient, token: str, session_id: str, cart_id: str):
        self._tc = tc
        self.token = token
        self.session_id = session_id
        self.cart_id = cart_id
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, url, **kw):
        return self._tc.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url, **kw):
        return self._tc.post(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self._tc.patch(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, url, **kw):
        return self._tc.delete(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    @property
    def raw(self) -> TestClient:
        return self._tc


@pytest.fixture()
def api(client) -> AuthClient:
    body = client.post("/sessions").json()
    return AuthClient(client, body["session_token"], body["session_id"], body["cart_id"])


@pytest.fixture()
def api2(client) -> AuthClient:
    body = client.post("/sessions").json()
    return AuthClient(client, body["session_token"], body["session_id"], body["cart_id"])


@pytest.fixture()
def admin_headers() -> dict:
    return {"X-Admin-Key": "test-admin-key"}


@pytest.fixture()
def shop(db_session):
    """A session created directly through the service layer (for service tests)."""
    from app.services.session_service import SessionService

    return SessionService(db_session).create_session()
