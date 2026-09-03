"""Audit service.

Business code calls this directly after a successful state change – audit
logging never depends on the LLM remembering to do it.

Neither ``metadata`` nor ``reason`` may contain secrets. ``metadata`` is
sanitised by key name and recursively; ``reason`` is scrubbed of obvious
bearer-style URLs/tokens before persist.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import AuditAction, AuditActor
from app.core.context import get_request_id
from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository
from app.utils.logging import get_logger

log = get_logger("audit")

_SECRET_HINTS = (
    "key", "secret", "token", "password", "signature", "authorization",
    "api_key", "short_url", "payment_link_url", "cookie", "bearer",
)
_URL_RE = re.compile(r"https?://\S+")


def _sanitize(value: Any, _key: str = "") -> Any:
    lowered = str(_key).lower()
    if any(hint in lowered for hint in _SECRET_HINTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _sanitize(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, _key) for v in value]
    return value


def _scrub_reason(reason: str) -> str:
    return _URL_RE.sub("[redacted-url]", reason or "")


class AuditService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditRepository(db)

    def log_event(
        self,
        *,
        actor: AuditActor,
        action: AuditAction,
        reason: str,
        session_id: str | None = None,
        order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        meta = _sanitize(metadata or {})
        entry = self.repo.add(
            actor=actor,
            action=action,
            reason=_scrub_reason(reason),
            meta_json=json.dumps(meta, default=str),
            session_id=session_id,
            order_id=order_id,
            request_id=get_request_id(),
        )
        log.info("AUDIT %s/%s :: %s", actor.value, action.value, _scrub_reason(reason))
        return entry

    def log_policy_block(
        self, *, reason: str, session_id: str | None = None, metadata: dict | None = None
    ) -> AuditLog:
        return self.log_event(
            actor=AuditActor.AGENT,
            action=AuditAction.POLICY_BLOCKED,
            reason=reason,
            session_id=session_id,
            metadata=metadata,
        )

    def log_payment_event(
        self,
        *,
        action: AuditAction,
        reason: str,
        order_id: str,
        session_id: str | None = None,
        actor: AuditActor = AuditActor.SYSTEM,
        metadata: dict | None = None,
    ) -> AuditLog:
        return self.log_event(
            actor=actor,
            action=action,
            reason=reason,
            session_id=session_id,
            order_id=order_id,
            metadata=metadata,
        )
