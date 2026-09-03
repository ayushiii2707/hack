"""Session model – one anonymous customer shopping interaction.

``upsell_shown`` is a hard, session-level guard. Once true it is NEVER reset
by any cart change; only a brand-new session gets a fresh upsell opportunity.

``token_hash`` is the peppered hash of the opaque bearer token issued to the
one client that owns this session. Authorisation for every cart/checkout/
payment/agent call is derived from it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import SessionState
from app.models.base import Base, TimestampMixin
from app.utils.ids import session_id


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=session_id)
    state: Mapped[SessionState] = mapped_column(
        SAEnum(SessionState, native_enum=False, length=32),
        default=SessionState.BROWSING,
        nullable=False,
    )

    # Ownership: peppered HMAC of the bearer token. Unique + indexed for O(1) auth.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    upsell_shown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    upsell_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    upsell_declined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # JSON-encoded list[{"role": "user"|"assistant", "content": str}] – MVP chat memory.
    chat_history: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    cart = relationship("Cart", back_populates="session", uselist=False, cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="session", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="session")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Session {self.id} {self.state} upsell_shown={self.upsell_shown}>"
