"""Product persistence. No business rules here – just database access."""
from __future__ import annotations

import json

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.catalog.normalizer import NormalizedProduct
from app.models.product import Product
from app.utils.time import utcnow


class ProductRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- reads ---
    def get_by_id(self, product_id: str) -> Product | None:
        return self.db.get(Product, product_id)

    def get_by_external_id(self, source: str, external_id: str) -> Product | None:
        stmt = select(Product).where(
            Product.source == source, Product.external_id == str(external_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_many(self, product_ids: list[str]) -> list[Product]:
        if not product_ids:
            return []
        stmt = select(Product).where(Product.id.in_(product_ids))
        return list(self.db.execute(stmt).scalars())

    def search(
        self,
        query: str | None = None,
        *,
        category: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        in_stock_only: bool = True,
        active_only: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Product]:
        stmt = select(Product)
        if active_only:
            stmt = stmt.where(Product.active.is_(True))
        if in_stock_only:
            stmt = stmt.where(Product.stock > 0)
        if category:
            stmt = stmt.where(func.lower(Product.category) == category.lower())
        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)
        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)
        if query:
            tokens = [t for t in query.lower().split() if len(t) > 1] or [query.lower()]

            def _matches(term: str):
                like = f"%{term}%"
                return or_(
                    func.lower(Product.name).like(like),
                    func.lower(Product.description).like(like),
                    func.lower(Product.brand).like(like),
                    func.lower(Product.category).like(like),
                    func.lower(Product.tags).like(like),
                )

            # Any token may match (keeps multi-word queries like "running shoes" useful);
            # rows matching more tokens rank first.
            stmt = stmt.where(or_(*[_matches(t) for t in tokens]))
            relevance = None
            for t in tokens:
                term = case((_matches(t), 1), else_=0)
                relevance = term if relevance is None else relevance + term
            stmt = stmt.order_by(relevance.desc(), Product.price.asc())
            return list(self.db.execute(stmt.limit(limit).offset(offset)).scalars())
        stmt = stmt.order_by(Product.price.asc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars())

    def list_by_category(self, category: str, *, limit: int = 50) -> list[Product]:
        return self.search(category=category, limit=limit)

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Product]:
        stmt = select(Product).order_by(Product.name).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars())

    def count(self) -> int:
        return self.db.execute(select(func.count()).select_from(Product)).scalar_one()

    def all_categories(self) -> list[str]:
        stmt = select(Product.category).where(Product.active.is_(True)).distinct()
        return sorted({c for (c,) in self.db.execute(stmt) if c})

    def all_external_ids(self, source: str) -> set[str]:
        rows = self.db.execute(
            select(Product.external_id).where(Product.source == source)
        )
        return {r[0] for r in rows}

    # --- writes ---
    def update_stock(self, product_id: str, new_stock: int) -> None:
        product = self.get_by_id(product_id)
        if product is not None:
            product.stock = max(0, new_stock)
            self.db.flush()

    def try_decrement_stock(self, product_id: str, qty: int) -> bool:
        """Atomically reserve ``qty`` units. Returns True only if it succeeded.

        The guarded UPDATE is race-safe on SQLite and PostgreSQL.
        """
        if qty <= 0:
            return True
        result = self.db.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.active.is_(True),
                Product.stock >= qty,
            )
            .values(stock=Product.stock - qty)
        )
        self.db.flush()
        return (result.rowcount or 0) == 1

    def increment_stock(self, product_id: str, qty: int) -> None:
        if qty <= 0:
            return
        self.db.execute(
            update(Product).where(Product.id == product_id).values(stock=Product.stock + qty)
        )
        self.db.flush()

    def deactivate_missing(self, source: str, seen_external_ids: set[str]) -> int:
        """Mark products no longer present in the provider feed as inactive."""
        if not seen_external_ids:
            return 0
        result = self.db.execute(
            update(Product)
            .where(
                Product.source == source,
                Product.active.is_(True),
                Product.external_id.notin_(seen_external_ids),
            )
            .values(active=False)
        )
        self.db.flush()
        return result.rowcount or 0

    def upsert(self, norm: NormalizedProduct) -> tuple[Product, bool]:
        """Insert or update by (source, external_id). Returns (product, created)."""
        existing = self.get_by_external_id(norm.source, norm.external_id)
        payload = dict(
            name=norm.name,
            description=norm.description,
            category=norm.category,
            brand=norm.brand,
            price=norm.price,
            currency=norm.currency,
            image_url=norm.image_url,
            product_url=norm.product_url,
            stock=norm.stock,
            sku=norm.sku,
            tags=json.dumps(norm.tags),
            last_synced_at=utcnow(),
        )
        if existing is None:
            product = Product(
                source=norm.source, external_id=norm.external_id, active=True, **payload
            )
            self.db.add(product)
            self.db.flush()
            return product, True
        # Local stock is authoritative once we start decrementing it at checkout;
        # don't let a periodic catalog sync clobber it.
        if settings.catalog_sync_preserve_local_stock:
            payload.pop("stock", None)
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.active = True
        self.db.flush()
        return existing, False
