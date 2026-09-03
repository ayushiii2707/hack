"""Abstract catalog provider interface.

The rest of the application must NOT know which concrete provider is in use.
Providers return raw provider-shaped dicts; the normalizer converts them to
our internal shape.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class RawProduct:
    """A provider-shaped product plus the provider identity."""

    source: str
    external_id: str
    payload: dict = field(default_factory=dict)


class CatalogProvider(abc.ABC):
    """Contract every external catalog source must satisfy."""

    source: str

    @abc.abstractmethod
    def fetch_products(self, *, limit: int = 100, skip: int = 0) -> list[RawProduct]:
        """Return a page of products from the provider."""

    @abc.abstractmethod
    def fetch_product(self, external_id: str) -> RawProduct | None:
        """Return a single product by its provider id, or None."""

    @abc.abstractmethod
    def search_products(self, query: str, *, limit: int = 20) -> list[RawProduct]:
        """Return provider-side search results (used only for sync, not runtime)."""
