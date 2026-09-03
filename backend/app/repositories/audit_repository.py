"""Audit log persistence (append-only)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import AuditAction, AuditActor
from app.models.audit_log import AuditLog


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(
        self,
        *,
        actor: AuditActor,
        action: AuditAction,
        reason: str,
        meta_json: str,
        session_id: str | None = None,
        order_id: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            session_id=session_id,
            order_id=order_id,
            actor=actor,
            action=action,
            reason=reason,
            meta=meta_json,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def list(
        self,
        *,
        session_id: str | None = None,
        order_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog)
        if session_id:
            stmt = stmt.where(AuditLog.session_id == session_id)
        if order_id:
            stmt = stmt.where(AuditLog.order_id == order_id)
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars())
