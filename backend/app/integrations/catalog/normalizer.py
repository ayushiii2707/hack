"""Convert provider-shaped products into our internal product shape.

This is the single choke point that protects the rest of the system from
external API schema drift.
"""
from __future__ import annotations

import math
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


def _safe_url(value: str) -> str:
    """Only allow http/https URLs from the external feed; drop anything else
    (javascript:, data:, file:, ...) so it can never reach the frontend."""
    v = (value or "").strip()
    if v[:7].lower() == "http://" or v[:8].lower() == "https://":
        return v[:1024]
    return ""


def normalize(raw: RawProduct) -> NormalizedProduct:
    p = raw.payload
    external_id = str(p.get("id") or raw.external_id or "").strip()
    name = str(p.get("title") or "").strip()
    if not external_id or not name:
        raise NormalizationError(f"missing id/title in {raw.source} product: {p!r}")

    raw_price = p.get("price")
    if raw_price is None:
        raise NormalizationError(f"missing price for {raw.source}:{external_id}")
    try:
        price_units = float(raw_price)
    except (TypeError, ValueError):
        raise NormalizationError(f"non-numeric price {raw_price!r} for {raw.source}:{external_id}")
    if not math.isfinite(price_units) or not 0 < price_units < 1_000_000:
        raise NormalizationError(f"price out of range ({raw_price!r}) for {raw.source}:{external_id}")
    try:
        price_paise = rupees_to_paise(price_units * settings.catalog_price_multiplier)
    except (ArithmeticError, ValueError):
        raise NormalizationError(f"unrepresentable price for {raw.source}:{external_id}")
    if not 0 < price_paise < 10**12:
        raise NormalizationError(f"non-positive/oversized price for {raw.source}:{external_id}")

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
        image_url=_safe_url(_first_str(p.get("images")) or str(p.get("thumbnail") or "")),
        product_url=_safe_url(str(p.get("product_url") or "")),
        stock=max(0, int(p.get("stock") or 0)),
        sku=str(p.get("sku") or "").strip(),
        tags=tags,
    )
