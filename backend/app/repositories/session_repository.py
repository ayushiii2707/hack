"""Session persistence."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.core.constants import SessionState
from app.models.session import Session


class SessionRepository:
    def __init__(self, db: DBSession):
        self.db = db

    def create(self) -> Session:
        session = Session(state=SessionState.BROWSING)
        self.db.add(session)
        self.db.flush()
        return session

    def get(self, session_id: str) -> Session | None:
        return self.db.get(Session, session_id)

    def set_state(self, session: Session, state: SessionState) -> None:
        session.state = state
        self.db.flush()

    def mark_upsell_shown(self, session: Session) -> None:
        session.upsell_shown = True
        self.db.flush()

    def mark_upsell_accepted(self, session: Session) -> None:
        session.upsell_accepted = True
        self.db.flush()

    def mark_upsell_declined(self, session: Session) -> None:
        session.upsell_declined = True
        self.db.flush()
