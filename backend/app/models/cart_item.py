"""CartItem model.

``unit_price`` is a SNAPSHOT taken in paise when the item is added, so cart
pricing stays deterministic even if the catalog price later changes.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.utils.ids import cart_item_id


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_item_cart_product"),
        CheckConstraint("quantity >= 1", name="ck_cart_item_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_cart_item_price_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=cart_item_id)
    cart_id: Mapped[str] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)  # paise snapshot

    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CartItem {self.product_id} x{self.quantity} @{self.unit_price}p>"
