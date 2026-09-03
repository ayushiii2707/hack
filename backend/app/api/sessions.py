"""Session APIs. A signed bearer token is the only identity in this MVP — no
accounts. The token is returned once from POST /sessions and also set as an
httpOnly cookie.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import require_session
from app.core.config import settings
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.session import SessionCreatedOut, SessionOut
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreatedOut, status_code=201, summary="Start a shopping session")
def create_session(response: Response, db: Session = Depends(get_db)):
    issued = SessionService(db).create_session()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        max_age=settings.session_token_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    return SessionCreatedOut.from_issued(issued.session, issued.token)


@router.get("/me", response_model=SessionOut, summary="Current session state")
def get_me(session: ShopSession = Depends(require_session)):
    return SessionOut.from_model(session)
