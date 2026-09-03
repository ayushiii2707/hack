"""Rate limiting: abuse-prone endpoints are throttled per client IP."""
from __future__ import annotations

import pytest


@pytest.fixture()
def _rl(monkeypatch):
    from app.core.config import settings
    from app.core.ratelimit import limiter

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_session_create_per_minute", 3)
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 2)
    limiter.reset()
    yield
    limiter.reset()


def test_session_creation_is_rate_limited(client, _rl):
    codes = [client.post("/sessions").status_code for _ in range(6)]
    assert codes.count(201) == 3
    assert 429 in codes
    assert client.post("/sessions").headers.get("Retry-After") is not None


def test_agent_endpoint_is_rate_limited(api, _rl):
    codes = []
    for _ in range(5):
        codes.append(api.post("/agent/chat", json={"message": "hi"}).status_code)
    assert 429 in codes


def test_health_is_never_rate_limited(client, _rl):
    for _ in range(50):
        assert client.get("/health").status_code == 200
