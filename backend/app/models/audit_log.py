"""AuditLog model – append-only business event trail.

Never store secrets (API keys, Razorpay secrets, Gemini keys, bearer tokens,
payment-link URLs) in ``meta`` or ``reason``. FKs are ``SET NULL`` on delete so
the trail survives session/order deletion (retention is an ops concern).
"""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import AuditAction, AuditActor
from app.models.base import Base, TimestampMixin
from app.utils.ids import audit_id


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=audit_id)
    # Denormalised copy so the trail is still attributable after a session is deleted.
    session_ref: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)

    actor: Mapped[AuditActor] = mapped_column(
        SAEnum(AuditActor, native_enum=False, length=24), nullable=False
    )
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=32), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # JSON-encoded dict; kept as text for SQLite portability.
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}", nullable=False)

    session = relationship("Session", back_populates="audit_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.actor}/{self.action} {self.reason[:40]!r}>"
