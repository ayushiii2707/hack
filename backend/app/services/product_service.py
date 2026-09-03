"""Product business logic. The agent reaches products ONLY through this layer.

    tool -> ProductService -> ProductRepository -> DB

Never the LLM straight to the repository.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientStockError,
    ProductInactiveError,
    ProductNotFoundError,
)
from app.models.product import Product
from app.repositories.product_repository import ProductRepository


@dataclass
class StockCheck:
    ok: bool
    available: int
    requested: int


def product_tags(p: Product) -> list[str]:
    try:
        return json.loads(p.tags) if p.tags else []
    except (ValueError, TypeError):
        return []


class ProductService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProductRepository(db)

    def search_products(
        self,
        query: str | None = None,
        *,
        category: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        limit: int = 20,
    ) -> list[Product]:
        return self.repo.search(
            query,
            category=category,
            min_price=min_price,
            max_price=max_price,
            in_stock_only=True,
            active_only=True,
            limit=limit,
        )

    def get_product(self, product_id: str, *, require_active: bool = True) -> Product:
        product = self.repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} was not found.")
        if require_active and not product.active:
            raise ProductInactiveError(f"'{product.name}' is not currently available.")
        return product

    def get_products_by_category(self, category: str, *, limit: int = 50) -> list[Product]:
        return self.repo.list_by_category(category, limit=limit)

    def list_categories(self) -> list[str]:
        return self.repo.all_categories()

    def check_stock(self, product_id: str, quantity: int) -> StockCheck:
        product = self.get_product(product_id)
        ok = product.stock >= quantity
        return StockCheck(ok=ok, available=product.stock, requested=quantity)

    def assert_purchasable(self, product_id: str, quantity: int) -> Product:
        """Raise unless ``quantity`` of an active, in-stock product can be sold."""
        product = self.get_product(product_id, require_active=True)
        if product.stock < quantity:
            raise InsufficientStockError(
                f"Only {product.stock} unit(s) of '{product.name}' are available.",
                details={"available": product.stock, "requested": quantity},
            )
        return product
