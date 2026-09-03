"""Session model – one customer shopping interaction.

``upsell_shown`` is a hard, session-level guard. Once true it is NEVER reset
by any cart change; only a brand-new session gets a fresh upsell opportunity.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Enum as SAEnum, String, Text
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

    upsell_shown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    upsell_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    upsell_declined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # JSON-encoded list[{"role": "user"|"assistant", "content": str}] – MVP chat memory.
    chat_history: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    cart = relationship("Cart", back_populates="session", uselist=False, cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="session", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Session {self.id} {self.state} upsell_shown={self.upsell_shown}>"
