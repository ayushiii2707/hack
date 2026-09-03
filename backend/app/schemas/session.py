"""Session API schemas."""
from __future__ import annotations

from pydantic import BaseModel

from app.models.session import Session


class SessionOut(BaseModel):
    session_id: str
    state: str
    cart_id: str
    upsell_shown: bool
    upsell_accepted: bool
    upsell_declined: bool

    @classmethod
    def from_model(cls, session: Session) -> SessionOut:
        return cls(
            session_id=session.id,
            state=session.state.value,
            cart_id=session.cart.id if session.cart else "",
            upsell_shown=session.upsell_shown,
            upsell_accepted=session.upsell_accepted,
            upsell_declined=session.upsell_declined,
        )


class SessionCreatedOut(SessionOut):
    # The bearer token is returned exactly once, here. Store it and send it as
    # `Authorization: Bearer <token>` (or rely on the httpOnly cookie).
    session_token: str

    @classmethod
    def from_issued(cls, session: Session, token: str) -> SessionCreatedOut:
        base = SessionOut.from_model(session)
        return cls(**base.model_dump(), session_token=token)
