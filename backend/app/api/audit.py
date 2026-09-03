"""Audit trail API – powers the merchant-facing transparency view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditEntryOut, AuditListOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListOut, summary="List audit events (newest first)")
def list_audit(
    db: Session = Depends(get_db),
    session_id: str | None = None,
    order_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = AuditRepository(db).list(
        session_id=session_id, order_id=order_id, limit=limit, offset=offset
    )
    return AuditListOut(
        items=[AuditEntryOut.from_model(r) for r in rows], count=len(rows)
    )
