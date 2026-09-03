"""The ONLY capabilities the LLM has.

Every tool: validate typed args -> policy check -> service call -> structured
result. There is deliberately no payment tool, no raw DB tool, no raw Razorpay
tool. A tool never raises to the model; it returns ``{"ok": false, "error": ...}``
so the agent can explain the failure but cannot escape it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.agent.policies import PolicyEngine
from app.agent.tool_schemas import (
    AddToCartArgs,
    EmptyArgs,
    GetProductArgs,
    RemoveFromCartArgs,
    SearchProductsArgs,
    UpdateCartQuantityArgs,
)
from app.core.constants import AuditAction, AuditActor
from app.core.exceptions import AppError, PolicyViolationError
from app.schemas.product import ProductOut
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.pricing_service import PricingService
from app.services.product_service import ProductService
from app.services.upsell_service import UpsellService
from app.utils.money import format_inr, rupees_to_paise


@dataclass
class ToolInvocation:
    name: str
    ok: bool
    result: dict


@dataclass
class ToolContext:
    db: Session
    session_id: str
    cart_id: str
    invocations: list[ToolInvocation] = field(default_factory=list)

    def record(self, name: str, ok: bool, result: dict) -> dict:
        self.invocations.append(ToolInvocation(name=name, ok=ok, result=result))
        return result


def _product_brief(p) -> dict:
    o = ProductOut.from_model(p)
    return {
        "product_id": o.id,
        "name": o.name,
        "brand": o.brand,
        "category": o.category,
        "price_paise": o.price,
        "price": o.price_display,
        "in_stock": o.in_stock,
        "stock": o.stock,
    }


def _err(ctx: ToolContext, name: str, code: str, message: str) -> str:
    return json.dumps(ctx.record(name, False, {"ok": False, "error": {"code": code, "message": message}}))


def _ok(ctx: ToolContext, name: str, payload: dict) -> str:
    return json.dumps(ctx.record(name, True, {"ok": True, **payload}))


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    db = ctx.db
    products = ProductService(db)
    carts = CartService(db)
    pricing = PricingService(db)
    upsell = UpsellService(db)
    checkout = CheckoutService(db)
    audit = AuditService(db)
    policy = PolicyEngine(db, ctx.session_id)

    def _cart_payload() -> dict:
        breakdown = pricing.get_price_breakdown(ctx.cart_id)
        return {
            "items": [
                {
                    "product_id": li.product_id,
                    "name": li.name,
                    "quantity": li.quantity,
                    "unit_price": format_inr(li.unit_price),
                    "line_total": format_inr(li.line_total),
                }
                for li in breakdown.line_items
            ],
            "subtotal": format_inr(breakdown.subtotal),
            "shipping": format_inr(breakdown.shipping),
            "total": format_inr(breakdown.total),
            "total_paise": breakdown.total,
        }

    # ---- search_products ----
    def search_products(query: str, max_price_rupees: float | None = None,
                        min_price_rupees: float | None = None, category: str | None = None) -> str:
        decision = policy.can_search_products()
        if not decision.allowed:
            return _err(ctx, "search_products", "POLICY_BLOCKED", decision.reason)
        max_p = rupees_to_paise(max_price_rupees) if max_price_rupees else None
        min_p = rupees_to_paise(min_price_rupees) if min_price_rupees else None
        found = products.search_products(
            query, category=category, min_price=min_p, max_price=max_p,
            limit=5,
        )
        audit.log_event(
            actor=AuditActor.CUSTOMER, action=AuditAction.PRODUCT_SEARCHED,
            reason=f"Searched '{query}'" + (f" under {format_inr(max_p)}" if max_p else ""),
            session_id=ctx.session_id,
            metadata={"query": query, "max_price": max_p, "results": len(found)},
        )
        db.commit()
        return _ok(ctx, "search_products", {
            "count": len(found),
            "products": [_product_brief(p) for p in found],
        })

    # ---- get_product ----
    def get_product(product_id: str) -> str:
        try:
            p = products.get_product(product_id, require_active=False)
        except AppError as exc:
            return _err(ctx, "get_product", exc.code, exc.message)
        brief = _product_brief(p)
        brief["description"] = p.description
        return _ok(ctx, "get_product", {"product": brief})

    # ---- add_to_cart ----
    def add_to_cart(product_id: str, quantity: int = 1) -> str:
        decision = policy.can_modify_cart(quantity=quantity)
        if not decision.allowed:
            return _err(ctx, "add_to_cart", "POLICY_BLOCKED", decision.reason)
        try:
            carts.add_item(ctx.cart_id, product_id, quantity, actor=AuditActor.AGENT)
        except PolicyViolationError as exc:
            return _err(ctx, "add_to_cart", "POLICY_BLOCKED", exc.message)
        except AppError as exc:
            return _err(ctx, "add_to_cart", exc.code, exc.message)
        return _ok(ctx, "add_to_cart", {"cart": _cart_payload()})

    # ---- update_cart_quantity ----
    def update_cart_quantity(product_id: str, quantity: int) -> str:
        decision = policy.can_modify_cart(quantity=quantity if quantity > 0 else None)
        if not decision.allowed:
            return _err(ctx, "update_cart_quantity", "POLICY_BLOCKED", decision.reason)
        try:
            carts.update_quantity(ctx.cart_id, product_id, quantity, actor=AuditActor.AGENT)
        except PolicyViolationError as exc:
            return _err(ctx, "update_cart_quantity", "POLICY_BLOCKED", exc.message)
        except AppError as exc:
            return _err(ctx, "update_cart_quantity", exc.code, exc.message)
        return _ok(ctx, "update_cart_quantity", {"cart": _cart_payload()})

    # ---- remove_from_cart ----
    def remove_from_cart(product_id: str) -> str:
        decision = policy.can_modify_cart()
        if not decision.allowed:
            return _err(ctx, "remove_from_cart", "POLICY_BLOCKED", decision.reason)
        try:
            carts.remove_item(ctx.cart_id, product_id, actor=AuditActor.AGENT)
        except AppError as exc:
            return _err(ctx, "remove_from_cart", exc.code, exc.message)
        return _ok(ctx, "remove_from_cart", {"cart": _cart_payload()})

    # ---- get_cart ----
    def get_cart() -> str:
        return _ok(ctx, "get_cart", {"cart": _cart_payload()})

    # ---- calculate_total ----
    def calculate_total() -> str:
        breakdown = pricing.get_price_breakdown(ctx.cart_id)
        return _ok(ctx, "calculate_total", {
            "subtotal": format_inr(breakdown.subtotal),
            "shipping": format_inr(breakdown.shipping),
            "tax": format_inr(breakdown.tax),
            "total": format_inr(breakdown.total),
            "total_paise": breakdown.total,
            "free_shipping_applied": breakdown.free_shipping_applied,
        })

    # ---- request_upsell ----
    def request_upsell() -> str:
        decision = policy.can_show_upsell()
        if not decision.allowed:
            return _err(ctx, "request_upsell", "POLICY_BLOCKED", decision.reason)
        try:
            reco = upsell.generate_recommendation(ctx.session_id)
        except AppError as exc:
            return _err(ctx, "request_upsell", exc.code, exc.message)
        return _ok(ctx, "request_upsell", {
            "product": _product_brief(reco.product),
            "reason": reco.reason,
            "price_cap": format_inr(reco.price_cap),
        })

    # ---- start_checkout ----
    def start_checkout() -> str:
        decision = policy.can_start_checkout()
        if not decision.allowed:
            return _err(ctx, "start_checkout", "POLICY_BLOCKED", decision.reason)
        try:
            review = checkout.start_checkout(ctx.session_id)
        except AppError as exc:
            return _err(ctx, "start_checkout", exc.code, exc.message)
        b = review.breakdown
        return _ok(ctx, "start_checkout", {
            "subtotal": format_inr(b.subtotal),
            "shipping": format_inr(b.shipping),
            "total": format_inr(b.total),
            "total_paise": b.total,
            "upsell_available": review.upsell_available,
            "upsell_pending": review.upsell_pending,
            "ready_for_payment": not review.issues and not review.upsell_pending,
            "note": "The customer must review the full total and click Pay themselves.",
        })

    # ---- get_checkout_status ----
    def get_checkout_status() -> str:
        review = checkout.get_summary(ctx.session_id)
        latest = checkout.orders.latest_for_session(ctx.session_id)
        return _ok(ctx, "get_checkout_status", {
            "total": format_inr(review.breakdown.total),
            "order_status": latest.status.value if latest else None,
            "upsell_pending": review.upsell_pending,
        })

    specs = [
        (search_products, "search_products",
         "Search the product catalog. Returns up to 5 matching in-stock products with prices.",
         SearchProductsArgs),
        (get_product, "get_product", "Get full details for one product by its product_id.",
         GetProductArgs),
        (add_to_cart, "add_to_cart",
         "Add a quantity of a product to the customer's cart. Quantity is capped by policy.",
         AddToCartArgs),
        (update_cart_quantity, "update_cart_quantity",
         "Set the absolute quantity of a product already in the cart (0 removes it).",
         UpdateCartQuantityArgs),
        (remove_from_cart, "remove_from_cart", "Remove a product from the cart.",
         RemoveFromCartArgs),
        (get_cart, "get_cart", "Return the current cart contents and authoritative totals.",
         EmptyArgs),
        (calculate_total, "calculate_total",
         "Return the authoritative price breakdown (subtotal, shipping, total).", EmptyArgs),
        (request_upsell, "request_upsell",
         "Ask the backend for the ONE allowed add-on recommendation for this cart. "
         "Only call this once, at cart review. If it is blocked, do not try again.",
         EmptyArgs),
        (start_checkout, "start_checkout",
         "Move to checkout review and return the full total to show the customer before payment. "
         "This does NOT take payment.", EmptyArgs),
        (get_checkout_status, "get_checkout_status",
         "Check the current order/payment status.", EmptyArgs),
    ]

    tools: list[StructuredTool] = []
    for fn, name, description, args_schema in specs:
        tools.append(
            StructuredTool.from_function(
                func=fn, name=name, description=description, args_schema=args_schema
            )
        )
    return tools
