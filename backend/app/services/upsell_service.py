"""Upsell recommendation.

Design constraints (all enforced here, in deterministic code):
  * at most ONE upsell per session – guarded by ``session.upsell_shown``
  * candidate must be in stock, not already in the cart, and within a
    configurable price cap (default 20% of the cart subtotal)
  * the recommendation carries a concrete, human reason – no "our AI predicts"
  * once shown, it is NEVER shown again, regardless of later cart changes

Scoring is a transparent weighted sum:
    score = 0.5*relevance + 0.3*complementary + 0.2*price_fit
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import AuditAction, AuditActor
from app.core.exceptions import UpsellAlreadyShownError, UpsellNotAvailableError
from app.models.product import Product
from app.repositories.product_repository import ProductRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.pricing_service import PricingService
from app.utils.money import calculate_percentage, format_inr

# Categories that commonly complete each other. Kept small and explicit so the
# reasoning is auditable ("complementary category: shoes -> socks").
COMPLEMENTARY_CATEGORIES: dict[str, set[str]] = {
    "mens-shoes": {"mens-shoes", "sports-accessories", "socks"},
    "womens-shoes": {"womens-shoes", "sports-accessories", "socks"},
    "sports-accessories": {"mens-shoes", "womens-shoes", "sports-accessories"},
    "laptops": {"mobile-accessories", "laptop-accessories", "tablets"},
    "smartphones": {"mobile-accessories", "smartphones"},
    "mobile-accessories": {"smartphones", "mobile-accessories"},
    "fragrances": {"beauty", "skin-care", "fragrances"},
    "beauty": {"beauty", "skin-care", "fragrances"},
    "skin-care": {"beauty", "skin-care", "fragrances"},
    "furniture": {"home-decoration", "furniture"},
    "home-decoration": {"furniture", "home-decoration", "kitchen-accessories"},
    "kitchen-accessories": {"groceries", "home-decoration", "kitchen-accessories"},
    "groceries": {"kitchen-accessories", "groceries"},
    "tops": {"womens-dresses", "womens-shoes", "womens-bags", "tops"},
    "mens-shirts": {"mens-shoes", "mens-watches", "sunglasses", "mens-shirts"},
}


@dataclass
class Candidate:
    product: Product
    score: float
    relevance: float
    complementary: float
    price_fit: float
    reason: str
    matched_tags: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    product: Product
    reason: str
    price_cap: int
    score: float
    breakdown: dict


def _tags(p: Product) -> set[str]:
    try:
        return {t.lower() for t in json.loads(p.tags)} if p.tags else set()
    except (ValueError, TypeError):
        return set()


class UpsellService:
    def __init__(self, db: Session):
        self.db = db
        self.products = ProductRepository(db)
        self.sessions = SessionRepository(db)
        self.carts = CartService(db)
        self.pricing = PricingService(db)
        self.audit = AuditService(db)

    # ---- candidate pipeline ----
    def get_candidates(self, cart) -> list[Product]:
        cart_product_ids = {it.product_id for it in cart.items}
        anchor_categories = {
            it.product.category for it in cart.items if it.product and it.product.category
        }
        pool: dict[str, Product] = {}
        wanted_categories = set(anchor_categories)
        for cat in anchor_categories:
            wanted_categories |= COMPLEMENTARY_CATEGORIES.get(cat, set())
        for cat in wanted_categories:
            for p in self.products.search(category=cat, in_stock_only=True, limit=25):
                if p.id not in cart_product_ids:
                    pool[p.id] = p
        return list(pool.values())

    def filter_candidates(self, candidates: list[Product], *, price_cap: int, cart) -> list[Product]:
        cart_product_ids = {it.product_id for it in cart.items}
        out = []
        for p in candidates:
            if p.id in cart_product_ids:
                continue
            if not p.active or p.stock <= 0:
                continue
            if p.price <= 0 or p.price > price_cap:
                continue
            out.append(p)
        return out

    def score_candidate(self, product: Product, *, cart) -> Candidate:
        anchor = max(cart.items, key=lambda it: it.unit_price * it.quantity)
        anchor_product = anchor.product
        anchor_cat = anchor_product.category if anchor_product else ""
        anchor_tags = _tags(anchor_product) if anchor_product else set()
        cand_tags = _tags(product)

        shared_tags = sorted(anchor_tags & cand_tags)
        relevance = min(1.0, 0.35 * len(shared_tags))
        if anchor_product and product.brand and product.brand == anchor_product.brand:
            relevance = min(1.0, relevance + 0.3)

        complementary = 0.0
        if product.category == anchor_cat:
            complementary = 0.6
        elif product.category in COMPLEMENTARY_CATEGORIES.get(anchor_cat, set()):
            complementary = 1.0

        subtotal = self.pricing.calculate_subtotal(cart) or 1
        ratio = product.price / subtotal
        price_fit = max(0.0, 1.0 - min(1.0, ratio / 0.2))  # best when well under the 20% cap

        score = 0.5 * relevance + 0.3 * complementary + 0.2 * price_fit

        anchor_name = anchor_product.name if anchor_product else "your cart"
        if complementary >= 1.0:
            reason = (
                f"Since you're buying {anchor_name}, {product.name} is a practical "
                f"add-on and stays within your budget."
            )
        elif shared_tags:
            reason = (
                f"{product.name} matches your pick on "
                f"{', '.join(shared_tags[:2])} and fits the price range."
            )
        elif product.brand and anchor_product and product.brand == anchor_product.brand:
            reason = f"{product.name} is from {product.brand}, the same brand as {anchor_name}."
        else:
            reason = f"{product.name} is a low-cost complement to {anchor_name}."

        return Candidate(
            product=product,
            score=round(score, 4),
            relevance=round(relevance, 4),
            complementary=round(complementary, 4),
            price_fit=round(price_fit, 4),
            reason=reason,
            matched_tags=shared_tags,
        )

    def select_best_candidate(self, cart, *, price_cap: int) -> Candidate | None:
        raw = self.get_candidates(cart)
        filtered = self.filter_candidates(raw, price_cap=price_cap, cart=cart)
        if not filtered:
            return None
        scored = [self.score_candidate(p, cart=cart) for p in filtered]
        scored.sort(key=lambda c: (c.score, -c.product.price), reverse=True)
        best = scored[0]
        return best if best.score > 0 else None

    # ---- public API ----
    def price_cap_for(self, cart) -> int:
        subtotal = self.pricing.calculate_subtotal(cart)
        return calculate_percentage(subtotal, settings.upsell_price_cap_percent)

    def peek(self, session_id: str) -> Recommendation | None:
        """Compute a candidate WITHOUT consuming the one-shot guard."""
        session = self.sessions.get(session_id)
        if session is None or session.upsell_shown:
            return None
        cart = self.carts.get_cart_for_session(session_id)
        if not cart.items:
            return None
        cap = self.price_cap_for(cart)
        best = self.select_best_candidate(cart, price_cap=cap)
        if best is None:
            return None
        return Recommendation(
            product=best.product,
            reason=best.reason,
            price_cap=cap,
            score=best.score,
            breakdown={
                "relevance": best.relevance,
                "complementary": best.complementary,
                "price_fit": best.price_fit,
                "matched_tags": best.matched_tags,
            },
        )

    def generate_recommendation(self, session_id: str) -> Recommendation:
        """Consume the one-shot guard and return the recommendation.

        Raises UpsellAlreadyShownError if an upsell was already shown, or
        UpsellNotAvailableError if no candidate qualifies.
        """
        session = self.sessions.get(session_id)
        if session is None:
            raise UpsellNotAvailableError("Session not found.")
        if session.upsell_shown:
            raise UpsellAlreadyShownError(
                "An upsell was already shown in this session; only one is allowed."
            )
        cart = self.carts.get_cart_for_session(session_id)
        if not cart.items:
            raise UpsellNotAvailableError("Cart is empty.")

        cap = self.price_cap_for(cart)
        best = self.select_best_candidate(cart, price_cap=cap)

        # The guard is consumed even when nothing qualifies, so we never retry.
        self.sessions.mark_upsell_shown(session)

        if best is None:
            # Nothing to accept/decline -> mark resolved so checkout isn't blocked.
            session.upsell_declined = True
            self.db.flush()
            self.audit.log_event(
                actor=AuditActor.AGENT,
                action=AuditAction.UPSELL_SHOWN,
                reason="No qualifying upsell candidate; one-shot opportunity consumed.",
                session_id=session_id,
                metadata={"price_cap": cap, "result": "none"},
            )
            self.db.commit()
            raise UpsellNotAvailableError("No suitable add-on is available for this cart.")

        self.audit.log_event(
            actor=AuditActor.AGENT,
            action=AuditAction.UPSELL_SHOWN,
            reason=best.reason,
            session_id=session_id,
            metadata={
                "candidate_product_id": best.product.id,
                "candidate_name": best.product.name,
                "candidate_price": best.product.price,
                "price_cap": cap,
                "score": best.score,
                "relevance": best.relevance,
                "complementary_score": best.complementary,
                "price_fit": best.price_fit,
                "matched_tags": best.matched_tags,
            },
        )
        self.db.commit()
        return Recommendation(
            product=best.product,
            reason=best.reason,
            price_cap=cap,
            score=best.score,
            breakdown={
                "relevance": best.relevance,
                "complementary": best.complementary,
                "price_fit": best.price_fit,
                "matched_tags": best.matched_tags,
                "price_cap_display": format_inr(cap),
            },
        )

    def accept(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if session is None:
            raise UpsellNotAvailableError("Session not found.")
        if not session.upsell_shown:
            raise UpsellNotAvailableError("No upsell has been shown yet.")
        if session.upsell_declined:
            raise UpsellAlreadyShownError("This upsell was already declined.")
        session.upsell_accepted = True
        self.db.flush()
        self.audit.log_event(
            actor=AuditActor.CUSTOMER,
            action=AuditAction.UPSELL_ACCEPTED,
            reason="Customer accepted the upsell recommendation.",
            session_id=session_id,
        )
        self.db.commit()
        return {"upsell_accepted": True}

    def decline(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if session is None:
            raise UpsellNotAvailableError("Session not found.")
        if not session.upsell_shown:
            raise UpsellNotAvailableError("No upsell has been shown yet.")
        session.upsell_declined = True
        self.db.flush()
        self.audit.log_event(
            actor=AuditActor.CUSTOMER,
            action=AuditAction.UPSELL_DECLINED,
            reason="Customer declined the upsell; it will not be shown again.",
            session_id=session_id,
        )
        self.db.commit()
        return {"upsell_declined": True}
