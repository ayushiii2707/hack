"""DummyJSON catalog provider.

Only DummyJSON-specific concerns live here: HTTP, pagination, response
parsing, provider error handling. No DB, no business rules, no upsell logic.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.constants import CATALOG_SOURCE_DUMMYJSON
from app.core.exceptions import ExternalProviderError
from app.integrations.catalog.base import CatalogProvider, RawProduct
from app.utils.logging import get_logger

log = get_logger("catalog.dummyjson")

_SELECT = "id,title,description,category,price,stock,brand,sku,tags,images,thumbnail"


class DummyJSONProvider(CatalogProvider):
    source = CATALOG_SOURCE_DUMMYJSON

    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0):
        self._base_url = (base_url or settings.catalog_base_url).rstrip("/")
        self._timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise ExternalProviderError(
                f"DummyJSON returned {exc.response.status_code} for {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(f"DummyJSON request failed for {path}: {exc}") from exc

    def _wrap(self, item: dict) -> RawProduct:
        return RawProduct(source=self.source, external_id=str(item.get("id")), payload=item)

    def fetch_products(self, *, limit: int = 100, skip: int = 0) -> list[RawProduct]:
        data = self._get(
            "/products", {"limit": limit, "skip": skip, "select": _SELECT}
        )
        items = data.get("products", [])
        log.info("fetched %d products (skip=%d)", len(items), skip)
        return [self._wrap(i) for i in items]

    def fetch_product(self, external_id: str) -> RawProduct | None:
        try:
            data = self._get(f"/products/{external_id}")
        except ExternalProviderError:
            return None
        if not data or "id" not in data:
            return None
        return self._wrap(data)

    def search_products(self, query: str, *, limit: int = 20) -> list[RawProduct]:
        data = self._get("/products/search", {"q": query, "limit": limit, "select": _SELECT})
        return [self._wrap(i) for i in data.get("products", [])]
