"""Order model – the authoritative amount lives here, in paise."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_CURRENCY, OrderStatus
from app.models.base import Base, TimestampMixin
from app.utils.ids import order_id


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=order_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cart_id: Mapped[str] = mapped_column(
        ForeignKey("carts.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # authoritative paise
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=24),
        default=OrderStatus.CREATED,
        nullable=False,
    )
    # Price breakdown snapshot (paise) captured at order creation.
    subtotal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shipping: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    receipt: Mapped[str | None] = mapped_column(String(40), nullable=True)

    session = relationship("Session", back_populates="orders")
    payments = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Payment.attempt_number",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.id} {self.status} {self.amount}p rzp={self.razorpay_order_id}>"
