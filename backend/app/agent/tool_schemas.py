"""Strict typed input schemas for every agent tool.

The LLM cannot pass arguments outside these bounds – pydantic rejects them
before any service is touched.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

_MAX_RUPEES = 10_000_000.0  # sane ceiling; rejects inf and absurd values


class SearchProductsArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=120, description="Free-text product query")
    max_price_rupees: float | None = Field(
        None, gt=0, lt=_MAX_RUPEES, description="Optional maximum unit price in rupees"
    )
    min_price_rupees: float | None = Field(
        None, ge=0, lt=_MAX_RUPEES, description="Optional minimum unit price in rupees"
    )
    category: str | None = Field(None, max_length=64)

    @field_validator("max_price_rupees", "min_price_rupees")
    @classmethod
    def _finite(cls, v: float | None) -> float | None:
        import math

        if v is not None and not math.isfinite(v):
            raise ValueError("price must be a finite number")
        return v


class GetProductArgs(BaseModel):
    product_id: str = Field(..., min_length=3, max_length=48)


class AddToCartArgs(BaseModel):
    product_id: str = Field(..., min_length=3, max_length=48)
    quantity: int = Field(1, ge=1, le=settings.max_item_quantity)


class UpdateCartQuantityArgs(BaseModel):
    product_id: str = Field(..., min_length=3, max_length=48)
    quantity: int = Field(..., ge=0, le=settings.max_item_quantity)


class RemoveFromCartArgs(BaseModel):
    product_id: str = Field(..., min_length=3, max_length=48)


class EmptyArgs(BaseModel):
    pass
