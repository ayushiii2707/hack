"""Per-request context (request id, owning session id) via contextvars.

Set by ``RequestContextMiddleware``; read by the logger and the audit service
so every log line and audit row can be correlated to one HTTP request.
"""
from __future__ import annotations

import contextvars

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("ctx_session_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_context_session_id(value: str | None) -> None:
    _session_id.set(value)


def get_context_session_id() -> str | None:
    return _session_id.get()
