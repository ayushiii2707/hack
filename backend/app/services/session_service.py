"""Session lifecycle. State transitions are validated against the
whitelist in ``constants.SESSION_TRANSITIONS`` – no arbitrary jumps.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.core.constants import (
    SESSION_TRANSITIONS,
    AuditAction,
    AuditActor,
    SessionState,
)
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.models.session import Session
from app.repositories.cart_repository import CartRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService


class SessionService:
    def __init__(self, db: DBSession):
        self.db = db
        self.sessions = SessionRepository(db)
        self.carts = CartRepository(db)
        self.audit = AuditService(db)

    def create_session(self) -> Session:
        session = self.sessions.create()
        self.carts.create(session.id)
        self.audit.log_event(
            actor=AuditActor.CUSTOMER,
            action=AuditAction.SESSION_CREATED,
            reason="New shopping session started (no account required).",
            session_id=session.id,
        )
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: str) -> Session:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} was not found.")
        return session

    def can_transition(self, current: SessionState, target: SessionState) -> bool:
        return target in SESSION_TRANSITIONS.get(current, set())

    def transition_state(
        self, session: Session, target: SessionState, *, reason: str = ""
    ) -> Session:
        if session.state == target:
            return session
        if not self.can_transition(session.state, target):
            raise InvalidStateTransitionError(
                f"Cannot move session from {session.state.value} to {target.value}.",
                details={"from": session.state.value, "to": target.value},
            )
        self.sessions.set_state(session, target)
        self.db.commit()
        self.db.refresh(session)
        return session
