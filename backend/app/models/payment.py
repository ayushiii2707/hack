"""Payment model – one row per attempt, never overwritten.

The demo shows ``FAILED`` attempt #1 followed by ``CAPTURED`` attempt #2, so
attempts must accumulate, not mutate.
"""
from __future__ import annotations

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import PaymentStatus
from app.models.base import Base, TimestampMixin
from app.utils.ids import payment_id


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_number", name="uq_payment_order_attempt"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=payment_id)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(24), default="checkout", nullable=False)

    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    razorpay_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    razorpay_payment_link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_link_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=16),
        default=PaymentStatus.CREATED,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    order = relationship("Order", back_populates="payments")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment {self.id} #{self.attempt_number} {self.status}>"
