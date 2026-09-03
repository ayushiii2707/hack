"""In-process token-bucket rate limiting.

Single-instance only. For a multi-instance deployment put a shared limiter
(Redis) in front, or in a reverse proxy — this is a floor, not a ceiling.
Limits are configurable via ``Settings.rate_limit_*``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class _Bucket:
    tokens: float
    last: float


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, *, key: str, bucket: str, per_minute: int) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        if not settings.rate_limit_enabled or per_minute <= 0:
            return True, 0
        rate = per_minute / 60.0
        now = time.monotonic()
        k = (bucket, key)
        with self._lock:
            b = self._buckets.get(k)
            if b is None:
                b = _Bucket(tokens=float(per_minute), last=now)
                self._buckets[k] = b
            elapsed = now - b.last
            b.tokens = min(float(per_minute), b.tokens + elapsed * rate)
            b.last = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0
            deficit = 1.0 - b.tokens
            return False, max(1, int(deficit / rate) + 1)

    def reset(self) -> None:  # test helper
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()


def bucket_for_path(method: str, path: str) -> tuple[str, int]:
    """Map a request to (bucket_name, per_minute)."""
    p = path.rstrip("/")
    if p == "/agent/chat":
        return "agent", settings.rate_limit_agent_per_minute
    if p == "/sessions" and method == "POST":
        return "session_create", settings.rate_limit_session_create_per_minute
    if p.startswith("/payments"):
        return "payment", settings.rate_limit_payment_per_minute
    if p.startswith("/webhooks"):
        return "webhook", settings.rate_limit_webhook_per_minute
    if p.startswith("/products/search") or (p == "/products" and method == "GET"):
        return "search", settings.rate_limit_search_per_minute
    return "default", settings.rate_limit_default_per_minute
