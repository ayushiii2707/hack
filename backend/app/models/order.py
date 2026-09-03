"""Order model – the authoritative amount lives here, in paise.

``open_cart_key`` enforces "at most one open order per cart" at the database
level (portable: a plain UNIQUE column that is set to ``cart_id`` while the
order is open and NULL once it reaches a terminal state; NULLs are distinct in
both SQLite and PostgreSQL).
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_CURRENCY, OrderStatus
from app.models.base import Base, TimestampMixin
from app.utils.ids import order_id

OPEN_ORDER_STATUSES = frozenset(
    {OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING, OrderStatus.PAYMENT_FAILED}
)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_order_amount_nonneg"),
        CheckConstraint("subtotal >= 0 AND shipping >= 0 AND tax >= 0", name="ck_order_parts_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=order_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cart_id: Mapped[str] = mapped_column(
        ForeignKey("carts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Non-null while the order is open; nulled on PAID/CANCELLED. UNIQUE.
    open_cart_key: Mapped[str | None] = mapped_column(String(48), nullable=True, unique=True)

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
    # True once local stock has been decremented for this order's items.
    stock_reserved: Mapped[bool] = mapped_column(default=False, nullable=False)

    session = relationship("Session", back_populates="orders")
    payments = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Payment.attempt_number",
    )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.id} {self.status} {self.amount}p rzp={self.razorpay_order_id}>"
