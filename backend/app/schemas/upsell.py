"""Upsell API schemas."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.product import ProductOut
from app.services.upsell_service import Recommendation
from app.utils.money import format_inr


class UpsellOut(BaseModel):
    available: bool
    product: ProductOut | None = None
    reason: str | None = None
    price_cap: int | None = None
    price_cap_display: str | None = None
    score: float | None = None
    breakdown: dict | None = None

    @classmethod
    def from_reco(cls, reco: Recommendation | None) -> UpsellOut:
        if reco is None:
            return cls(available=False)
        return cls(
            available=True,
            product=ProductOut.from_model(reco.product),
            reason=reco.reason,
            price_cap=reco.price_cap,
            price_cap_display=format_inr(reco.price_cap),
            score=reco.score,
            breakdown=reco.breakdown,
        )


class UpsellDecisionOut(BaseModel):
    upsell_accepted: bool = False
    upsell_declined: bool = False
