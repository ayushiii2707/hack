"""Secure-by-default configuration."""
from __future__ import annotations

from app.core.config import Settings


def _prod(**over) -> Settings:
    base = dict(
        environment="production",
        session_token_secret="x" * 40,
        database_url="postgresql+psycopg://u:p@h/db",
        trusted_hosts="app.example.com",
        cors_origins="https://app.example.com",
        session_cookie_secure=True,
        razorpay_key_id="rzp_live_x",
        razorpay_key_secret="s",
        razorpay_webhook_secret="whsec",
        enable_demo_endpoints=False,
    )
    base.update(over)
    return Settings(**base)


def test_safe_production_config_has_no_problems():
    assert _prod().validate_for_environment() == []


def test_missing_session_secret_blocks_production():
    assert any("SESSION_TOKEN_SECRET" in p for p in _prod(session_token_secret="").validate_for_environment())


def test_missing_webhook_secret_blocks_production_when_razorpay_set():
    problems = _prod(razorpay_webhook_secret="").validate_for_environment()
    assert any("RAZORPAY_WEBHOOK_SECRET" in p for p in problems)


def test_demo_endpoints_block_production():
    assert any("DEMO" in p for p in _prod(enable_demo_endpoints=True).validate_for_environment())


def test_sqlite_blocks_production():
    assert any("SQLite" in p for p in _prod(database_url="sqlite:///./x.db").validate_for_environment())


def test_wildcard_hosts_block_production():
    assert any("TRUSTED_HOSTS" in p for p in _prod(trusted_hosts="*").validate_for_environment())


def test_development_generates_ephemeral_secret():
    s = Settings(environment="development", session_token_secret="")
    assert len(s.session_token_secret) >= 32  # auto-generated for dev


def test_default_gemini_model_is_not_a_retired_name():
    # gemini-2.0-flash was retired by Google (API returns 404 NOT_FOUND);
    # a fresh deploy on the default must use a model that still exists.
    default = Settings().gemini_model
    assert default and "flash" in default
    assert default != "gemini-2.0-flash"
