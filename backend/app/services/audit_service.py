"""Audit service.

Business code calls this directly after a successful state change – audit
logging never depends on the LLM remembering to do it.

``metadata`` is sanitised: any key that looks secret is dropped before persist.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import AuditAction, AuditActor
from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository
from app.utils.logging import get_logger

log = get_logger("audit")

_SECRET_HINTS = ("key", "secret", "token", "password", "signature", "authorization", "api_key")


def _sanitize(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    clean: dict[str, Any] = {}
    for key, value in meta.items():
        lowered = str(key).lower()
        if any(hint in lowered for hint in _SECRET_HINTS):
            clean[key] = "[redacted]"
        else:
            clean[key] = value
    return clean


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
        meta = _sanitize(metadata)
        entry = self.repo.add(
            actor=actor,
            action=action,
            reason=reason,
            meta_json=json.dumps(meta, default=str),
            session_id=session_id,
            order_id=order_id,
        )
        log.info("AUDIT %s/%s :: %s", actor.value, action.value, reason)
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
