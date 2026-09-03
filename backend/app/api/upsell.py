"""Upsell APIs (session-scoped). The one-shot guard is enforced atomically in
UpsellService; these are all POSTs because they mutate session state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_session
from app.core.exceptions import UpsellAlreadyShownError, UpsellNotAvailableError
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.upsell import UpsellDecisionOut, UpsellOut
from app.services.upsell_service import UpsellService

router = APIRouter(prefix="/upsell", tags=["upsell"])


@router.post("", response_model=UpsellOut, summary="Get the one upsell for my session")
def get_upsell(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    svc = UpsellService(db)
    try:
        return UpsellOut.from_reco(svc.generate_recommendation(session.id))
    except UpsellAlreadyShownError:
        return UpsellOut(available=False, reason="An upsell was already shown in this session.")
    except UpsellNotAvailableError:
        return UpsellOut(available=False, reason="No suitable add-on is available for this cart.")


@router.get("/preview", response_model=UpsellOut, summary="Preview without consuming the guard")
def preview_upsell(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return UpsellOut.from_reco(UpsellService(db).peek(session.id))


@router.post("/accept", response_model=UpsellDecisionOut)
def accept_upsell(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return UpsellDecisionOut(**UpsellService(db).accept(session.id))


@router.post("/decline", response_model=UpsellDecisionOut)
def decline_upsell(session: ShopSession = Depends(require_session), db: Session = Depends(get_db)):
    return UpsellDecisionOut(**UpsellService(db).decline(session.id))
