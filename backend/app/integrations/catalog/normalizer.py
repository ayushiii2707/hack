"""Convert provider-shaped products into our internal product shape.

This is the single choke point that protects the rest of the system from
external API schema drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.core.constants import DEFAULT_CURRENCY
from app.integrations.catalog.base import RawProduct
from app.utils.money import rupees_to_paise


@dataclass
class NormalizedProduct:
    external_id: str
    source: str
    name: str
    description: str
    category: str
    brand: str
    price: int  # integer paise
    currency: str
    image_url: str
    product_url: str
    stock: int
    sku: str
    tags: list[str] = field(default_factory=list)


class NormalizationError(ValueError):
    """Raised when a raw product cannot be normalized into a valid product."""


def _first_str(value, default: str = "") -> str:
    if isinstance(value, list):
        return str(value[0]) if value else default
    if value is None:
        return default
    return str(value)


def normalize(raw: RawProduct) -> NormalizedProduct:
    p = raw.payload
    external_id = str(p.get("id") or raw.external_id or "").strip()
    name = str(p.get("title") or "").strip()
    if not external_id or not name:
        raise NormalizationError(f"missing id/title in {raw.source} product: {p!r}")

    raw_price = p.get("price")
    if raw_price is None:
        raise NormalizationError(f"missing price for {raw.source}:{external_id}")
    price_paise = rupees_to_paise(float(raw_price) * settings.catalog_price_multiplier)
    if price_paise <= 0:
        raise NormalizationError(f"non-positive price for {raw.source}:{external_id}")

    tags = p.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]

    category = str(p.get("category") or "").strip().lower()
    if category and category not in tags:
        tags.append(category)

    return NormalizedProduct(
        external_id=external_id,
        source=raw.source,
        name=name,
        description=str(p.get("description") or "").strip(),
        category=category,
        brand=str(p.get("brand") or "").strip(),
        price=price_paise,
        currency=DEFAULT_CURRENCY,
        image_url=_first_str(p.get("images")) or str(p.get("thumbnail") or ""),
        product_url=str(p.get("product_url") or ""),
        stock=max(0, int(p.get("stock") or 0)),
        sku=str(p.get("sku") or "").strip(),
        tags=tags,
    )
