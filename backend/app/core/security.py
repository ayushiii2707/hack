"""Security primitives.

V1 has no user accounts / passwords — in line with the "no forced account
creation" product goal. Instead each anonymous shopping session is issued an
opaque bearer token. The token is never stored; only a peppered hash of it is
persisted on the session row, so a database leak cannot be replayed without the
server-side pepper (``SESSION_TOKEN_SECRET``).

This module also holds the HMAC helpers used by the Razorpay integration and
webhook handler.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from app.core.config import settings


# --- generic HMAC helpers ---
def hmac_sha256_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --- session bearer tokens ---
def new_session_token() -> str:
    """A high-entropy, URL-safe opaque token handed to exactly one client."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Peppered hash stored on the session row (never the raw token)."""
    pepper = settings.session_token_secret or "dev-insecure-pepper"
    return hmac_sha256_hex(pepper, token)


def verify_admin_key(provided: str | None) -> bool:
    """Constant-time check of an admin key. Returns False if admin is unconfigured."""
    if not settings.admin_api_key or not provided:
        return False
    return hmac.compare_digest(provided, settings.admin_api_key)
