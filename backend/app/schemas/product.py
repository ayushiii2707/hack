"""Product API schemas."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.models.product import Product
from app.utils.money import format_inr


class ProductOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    brand: str
    price: int = Field(description="Authoritative unit price in integer paise")
    price_display: str
    currency: str
    image_url: str
    stock: int
    in_stock: bool
    sku: str
    tags: list[str]
    active: bool

    @classmethod
    def from_model(cls, p: Product) -> ProductOut:
        try:
            tags = json.loads(p.tags) if p.tags else []
        except (ValueError, TypeError):
            tags = []
        return cls(
            id=p.id,
            name=p.name,
            description=p.description,
            category=p.category,
            brand=p.brand,
            price=p.price,
            price_display=format_inr(p.price),
            currency=p.currency,
            image_url=p.image_url,
            stock=p.stock,
            in_stock=p.stock > 0,
            sku=p.sku,
            tags=tags,
            active=p.active,
        )


class ProductListOut(BaseModel):
    items: list[ProductOut]
    count: int


class CatalogSyncOut(BaseModel):
    fetched: int
    created: int
    updated: int
    skipped: int
    deactivated: int = 0
    error_count: int
