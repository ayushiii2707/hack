"""Upsell APIs. The session-level one-shot guard is enforced by UpsellService."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import UpsellAlreadyShownError, UpsellNotAvailableError
from app.database.database import get_db
from app.schemas.upsell import UpsellDecisionOut, UpsellOut
from app.services.upsell_service import UpsellService

router = APIRouter(prefix="/upsell", tags=["upsell"])


@router.get("/{session_id}", response_model=UpsellOut, summary="Get the one upsell for this session")
def get_upsell(
    session_id: str,
    db: Session = Depends(get_db),
    peek: bool = Query(False, description="Preview without consuming the one-shot guard"),
):
    svc = UpsellService(db)
    if peek:
        return UpsellOut.from_reco(svc.peek(session_id))
    try:
        return UpsellOut.from_reco(svc.generate_recommendation(session_id))
    except UpsellAlreadyShownError:
        return UpsellOut(available=False, reason="An upsell was already shown in this session.")
    except UpsellNotAvailableError:
        return UpsellOut(available=False, reason="No suitable add-on is available for this cart.")


@router.post("/{session_id}/accept", response_model=UpsellDecisionOut)
def accept_upsell(session_id: str, db: Session = Depends(get_db)):
    return UpsellDecisionOut(**UpsellService(db).accept(session_id))


@router.post("/{session_id}/decline", response_model=UpsellDecisionOut)
def decline_upsell(session_id: str, db: Session = Depends(get_db)):
    return UpsellDecisionOut(**UpsellService(db).decline(session_id))
