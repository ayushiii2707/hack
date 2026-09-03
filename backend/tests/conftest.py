"""Shared test fixtures: an isolated in-memory database per test."""
from __future__ import annotations

import os

# Pin config for deterministic tests, overriding any local .env.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENVIRONMENT"] = "test"
os.environ["CATALOG_PRICE_MULTIPLIER"] = "35"
os.environ["MAX_ITEM_QUANTITY"] = "5"
os.environ["UPSELL_PRICE_CAP_PERCENT"] = "20"
os.environ["SHIPPING_FEE"] = "500"
os.environ["FREE_SHIPPING_THRESHOLD"] = "200000"
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_dummy")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "dummysecret")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "whsec_dummy")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  populate metadata
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
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    TestingSessionLocal = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, future=True
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine):
    TestingSessionLocal = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, future=True
    )

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_rzp(monkeypatch):
    """Patch every get_razorpay_client() seam with one shared fake client.

    Autouse so no test can accidentally reach the real Razorpay API.
    """
    from tests.factories import FakeRazorpayClient

    client = FakeRazorpayClient()
    for mod in ("app.services.payment_service", "app.api.webhooks"):
        monkeypatch.setattr(f"{mod}.get_razorpay_client", lambda: client, raising=True)
    return client
