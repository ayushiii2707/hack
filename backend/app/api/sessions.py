"""Session APIs. A session id is the only identity in this MVP – no accounts."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.schemas.session import SessionOut
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201, summary="Start a shopping session")
def create_session(db: Session = Depends(get_db)):
    session = SessionService(db).create_session()
    return SessionOut.from_model(session)


@router.get("/{session_id}", response_model=SessionOut, summary="Get session state")
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = SessionService(db).get_session(session_id)
    return SessionOut.from_model(session)
