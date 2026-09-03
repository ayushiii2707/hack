"""Security helpers.

V1 deliberately has NO user accounts / passwords – a session id is the only
identity, in line with the "no forced account creation" product goal. This
module holds signature-verification helpers used by the Razorpay integration
and webhook handler (populated in Phase 7).
"""
from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
