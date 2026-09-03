"""Cart model – one active cart per session."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CartStatus
from app.models.base import Base, TimestampMixin
from app.utils.ids import cart_id


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=cart_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    status: Mapped[CartStatus] = mapped_column(
        SAEnum(CartStatus, native_enum=False, length=16),
        default=CartStatus.ACTIVE,
        nullable=False,
    )

    session = relationship("Session", back_populates="cart")
    items = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItem.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Cart {self.id} {self.status} items={len(self.items)}>"
