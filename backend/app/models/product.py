"""Product model – the internal runtime source of truth for catalog data."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import DEFAULT_CURRENCY
from app.models.base import Base, TimestampMixin
from app.utils.ids import product_id


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_product_source_external"),
        CheckConstraint("price >= 0", name="ck_product_price_nonneg"),
        CheckConstraint("stock >= 0", name="ck_product_stock_nonneg"),
        Index("ix_product_category", "category"),
        Index("ix_product_active", "active"),
        Index("ix_product_sku", "sku"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=product_id)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    # Authoritative price in integer paise.
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)

    image_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    product_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)

    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # JSON-encoded list[str]; kept as text for SQLite portability.
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Product {self.id} {self.name!r} {self.price}p stock={self.stock}>"
