"""Audit trail API.

By default a caller only sees their OWN session's events. Cross-session /
merchant views require the admin key (``X-Admin-Key``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_session
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditEntryOut, AuditListOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListOut, summary="My audit events (newest first)")
def list_my_audit(
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = AuditRepository(db).list(session_id=session.id, limit=limit, offset=offset)
    return AuditListOut(items=[AuditEntryOut.from_model(r) for r in rows], count=len(rows))


@router.get(
    "/admin",
    response_model=AuditListOut,
    dependencies=[Depends(require_admin)],
    tags=["admin"],
    summary="Cross-session audit events (admin only)",
)
def list_all_audit(
    db: Session = Depends(get_db),
    session_id: str | None = None,
    order_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = AuditRepository(db).list(
        session_id=session_id, order_id=order_id, limit=limit, offset=offset
    )
    return AuditListOut(items=[AuditEntryOut.from_model(r) for r in rows], count=len(rows))
