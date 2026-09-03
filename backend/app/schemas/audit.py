"""Audit API schemas."""
from __future__ import annotations

import json

from pydantic import BaseModel

from app.models.audit_log import AuditLog
from app.utils.time import isoformat


class AuditEntryOut(BaseModel):
    id: str
    session_id: str | None
    order_id: str | None
    actor: str
    action: str
    reason: str
    metadata: dict
    created_at: str | None

    @classmethod
    def from_model(cls, a: AuditLog) -> "AuditEntryOut":
        try:
            meta = json.loads(a.meta) if a.meta else {}
        except (ValueError, TypeError):
            meta = {}
        return cls(
            id=a.id,
            session_id=a.session_id,
            order_id=a.order_id,
            actor=a.actor.value,
            action=a.action.value,
            reason=a.reason,
            metadata=meta,
            created_at=isoformat(a.created_at),
        )


class AuditListOut(BaseModel):
    items: list[AuditEntryOut]
    count: int
