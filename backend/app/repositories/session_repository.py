"""Session persistence."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from app.core.constants import SessionState
from app.models.session import Session
from app.utils.time import utcnow


class SessionRepository:
    def __init__(self, db: DBSession):
        self.db = db

    def create(self, *, token_hash: str) -> Session:
        session = Session(
            state=SessionState.BROWSING,
            token_hash=token_hash,
            token_issued_at=utcnow(),
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get(self, session_id: str) -> Session | None:
        return self.db.get(Session, session_id)

    def get_by_token_hash(self, token_hash: str) -> Session | None:
        return self.db.execute(
            select(Session).where(Session.token_hash == token_hash)
        ).scalar_one_or_none()

    def set_state(self, session: Session, state: SessionState) -> None:
        session.state = state
        self.db.flush()

    def try_claim_upsell(self, session_id: str) -> bool:
        """Atomically flip ``upsell_shown`` False -> True.

        Returns True only for the caller that won the race. This is the
        one-shot-upsell guarantee and it holds under concurrency on both
        SQLite (serialised writes) and PostgreSQL.
        """
        result = self.db.execute(
            update(Session)
            .where(Session.id == session_id, Session.upsell_shown.is_(False))
            .values(upsell_shown=True)
        )
        self.db.flush()
        return (result.rowcount or 0) == 1

    def mark_upsell_accepted(self, session: Session) -> None:
        session.upsell_accepted = True
        self.db.flush()

    def mark_upsell_declined(self, session: Session) -> None:
        session.upsell_declined = True
        self.db.flush()
