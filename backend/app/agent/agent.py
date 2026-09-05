"""Agent orchestrator.

    User -> API -> Agent (LangChain/Gemini) -> constrained tools -> services -> DB

The LLM only orchestrates conversation and picks among the allowed tools.
UI actions returned to the frontend are built HERE from what the tools actually
did – the model never invents an action type.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState, ChatTurn
from app.agent.tools import ToolContext, build_tools
from app.core.constants import UIActionType
from app.repositories.session_repository import SessionRepository
from app.services.cart_service import CartService
from app.utils.logging import get_logger

log = get_logger("agent")

# tool name -> UI action it implies (backend-controlled, not LLM-controlled)
_TOOL_ACTION: dict[str, UIActionType] = {
    "search_products": UIActionType.SHOW_PRODUCTS,
    "get_product": UIActionType.SHOW_PRODUCTS,
    "add_to_cart": UIActionType.SHOW_CART,
    "update_cart_quantity": UIActionType.SHOW_CART,
    "remove_from_cart": UIActionType.SHOW_CART,
    "get_cart": UIActionType.SHOW_CART,
    "calculate_total": UIActionType.SHOW_CART,
    "request_upsell": UIActionType.SHOW_UPSELL,
    "accept_upsell": UIActionType.SHOW_UPSELL,
    "decline_upsell": UIActionType.SHOW_UPSELL,
    "start_checkout": UIActionType.SHOW_CHECKOUT,
    "get_checkout_status": UIActionType.SHOW_CHECKOUT,
}


@dataclass
class UIAction:
    type: str
    payload: dict = field(default_factory=dict)


@dataclass
class AgentResponse:
    message: str
    state: str
    actions: list[UIAction]
    tool_calls: list[str]


def _build_actions(ctx: ToolContext) -> list[UIAction]:
    """Deterministically derive UI actions from executed tool calls."""
    actions: list[UIAction] = []
    seen: set[str] = set()
    for inv in ctx.invocations:
        action_type = _TOOL_ACTION.get(inv.name)
        if action_type is None:
            continue
        if not inv.ok:
            # A blocked / failed tool call never drives a UI panel.
            continue
        key = action_type.value
        if inv.name == "search_products" and inv.ok:
            ids = [p["product_id"] for p in inv.result.get("products", [])]
            actions.append(UIAction(UIActionType.SHOW_PRODUCTS.value, {"product_ids": ids}))
            seen.add(key)
        elif inv.name == "get_product" and inv.ok:
            pid = inv.result.get("product", {}).get("product_id")
            actions.append(UIAction(UIActionType.SHOW_PRODUCTS.value,
                                    {"product_ids": [pid] if pid else []}))
            seen.add(key)
        elif inv.name == "request_upsell" and inv.ok:
            actions.append(UIAction(UIActionType.SHOW_UPSELL.value, {
                "product_id": inv.result.get("product", {}).get("product_id"),
                "reason": inv.result.get("reason"),
            }))
            seen.add(key)
        elif key not in seen:
            actions.append(UIAction(key, {}))
            seen.add(key)
    # De-dupe repeated cart/checkout actions, keep the last of each type.
    collapsed: dict[str, UIAction] = {}
    ordered: list[UIAction] = []
    for a in actions:
        if a.type in (UIActionType.SHOW_PRODUCTS.value, UIActionType.SHOW_UPSELL.value):
            ordered.append(a)
        else:
            collapsed[a.type] = a
    ordered.extend(collapsed.values())
    return ordered


def _to_lc_messages(history: list[ChatTurn], new_message: str) -> list:
    msgs: list = [SystemMessage(content=SYSTEM_PROMPT)]
    for turn in history:
        if turn.role == "assistant":
            msgs.append(AIMessage(content=turn.content))
        else:
            msgs.append(HumanMessage(content=turn.content))
    msgs.append(HumanMessage(content=new_message))
    return msgs


def _final_text(result: dict) -> str:
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
        if isinstance(msg, AIMessage) and isinstance(msg.content, list):
            parts = [p.get("text", "") for p in msg.content if isinstance(p, dict)]
            joined = " ".join(x for x in parts if x).strip()
            if joined:
                return joined
    return "Done."


_FILLER = {
    "show", "me", "find", "search", "for", "some", "a", "an", "the", "please",
    "i", "need", "want", "looking", "under", "below", "less", "than", "budget",
    "of", "up", "to", "around", "rs", "rs.", "inr", "₹",
}


def _parse_price(text: str) -> int | None:
    import re

    m = re.search(r"(?:under|below|less than|<|upto|up to)\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*)", text)
    if not m:
        return None
    return int(m.group(1).replace(",", "")) * 100


_ADD_RE = re.compile(
    r"add\s+(?:\d+\s+)?(.+?)\s+to\s+(?:my\s+)?cart|^add\s+(.+)$|buy\s+(.+)", re.I
)
_REMOVE_RE = re.compile(
    r"remove\s+(.+?)\s+from\s+(?:my\s+)?cart|^remove\s+(.+)$|delete\s+(.+?)\s+from\s+(?:my\s+)?cart",
    re.I,
)
_QTY_RE = re.compile(
    r"(?:set|make|change)\s+(.+?)\s+(?:quantity\s+)?to\s+(\d+)|(.+?)\s+quantity\s+to\s+(\d+)",
    re.I,
)

# Pronouns/ordinals carry no explicit product identity for a keyword router
# (no conversation memory here); refusing to guess is intentional — an LLM
# with real chat history is expected to resolve these, but that path requires
# GEMINI_API_KEY and is UNVERIFIED in an environment without one.
_AMBIGUOUS_REFERENTS = {
    "it", "that", "this", "them", "those", "one", "the first one", "the last one",
    "the first", "the last", "this one", "that one",
}


def _resolve_named_product(products_svc, name: str):
    name = name.strip().strip(".").strip()
    if not name or name.lower() in _AMBIGUOUS_REFERENTS:
        return None
    found = products_svc.search_products(name, limit=1)
    return found[0] if found else None


def _run_fallback(ctx: ToolContext, tools, message: str) -> str:
    """Deterministic intent router used when GEMINI_API_KEY is not set.

    Still goes through the same tools -> policies -> services path. This
    router has no conversation memory of prior results, so it can only act on
    an EXPLICITLY NAMED product ("add the running shoes to my cart") — it
    deliberately refuses pronoun/ordinal references ("add it", "the first
    one") rather than guessing which product the customer means. Resolving
    those requires an actual LLM turn with chat history (GEMINI_API_KEY).
    """
    from app.services.product_service import ProductService

    by_name = {t.name: t for t in tools}
    text = message.lower().strip()

    def call(name: str, **kw) -> dict:
        return json.loads(by_name[name].invoke(kw))

    products_svc = ProductService(ctx.db)

    m = _QTY_RE.search(text)
    if m:
        name = next((g for g in (m.group(1), m.group(3)) if g), "")
        qty = next((g for g in (m.group(2), m.group(4)) if g), None)
        product = _resolve_named_product(products_svc, name)
        if product is None:
            return (
                f"I'm not sure which item you mean by '{name.strip()}' — please name the "
                "product (or its exact name from a search result)."
            )
        res = call("update_cart_quantity", product_id=product.id, quantity=int(qty))
        if not res.get("ok"):
            return f"I couldn't update the quantity: {res['error']['message']}"
        return f"Updated {product.name} to quantity {qty}. Your cart total is now {res['cart']['total']}."

    m = _REMOVE_RE.search(text)
    if m:
        name = next((g for g in m.groups() if g), "")
        product = _resolve_named_product(products_svc, name)
        if product is None:
            return (
                f"I'm not sure which item you mean by '{name.strip()}' — please name the "
                "product you'd like removed."
            )
        res = call("remove_from_cart", product_id=product.id)
        if not res.get("ok"):
            return f"I couldn't remove that: {res['error']['message']}"
        return f"Removed {product.name} from your cart. Total is now {res['cart']['total']}."

    m = _ADD_RE.search(text)
    if m:
        name = next((g for g in m.groups() if g), "")
        product = _resolve_named_product(products_svc, name)
        if product is None:
            return (
                f"I'm not sure which item you mean by '{name.strip()}' — please name the exact "
                "product (try searching first so I can show you options)."
            )
        res = call("add_to_cart", product_id=product.id, quantity=1)
        if not res.get("ok"):
            return f"I couldn't add that: {res['error']['message']}"
        return f"Added {product.name} to your cart. Your cart total is now {res['cart']['total']}."

    if any(w in text for w in ("checkout", "check out", "review my order", "ready to pay", "proceed")):
        res = call("start_checkout")
        if not res.get("ok"):
            return f"I couldn't start checkout: {res['error']['message']}"
        return (
            f"Here's your order. Subtotal {res['subtotal']}, shipping {res['shipping']}, "
            f"total {res['total']}. Review it and click Pay when you're ready."
        )

    if any(w in text for w in ("decline", "no thanks", "not interested", "skip it")):
        res = call("decline_upsell")
        if not res.get("ok"):
            return f"I couldn't decline that: {res['error']['message']}"
        return "No problem, I won't suggest anything else for this order."

    if any(w in text for w in ("accept the", "accept it", "i'll take it", "sounds good")):
        res = call("accept_upsell")
        if not res.get("ok"):
            return f"I couldn't record that: {res['error']['message']}"
        return "Great, I've noted that — add it to your cart and it'll be included at checkout."

    if any(w in text for w in ("anything else", "add-on", "add on", "complementary", "goes with",
                                "pair well", "recommend", "suggestion", "go with")):
        res = call("request_upsell")
        if not res.get("ok"):
            return "There's no additional suggestion for this cart."
        return f"{res['reason']} It's {res['product']['price']}. Add it if you'd like."

    if any(w in text for w in ("my cart", "the cart", "what's in", "show cart", "view cart",
                                "total", "how much")):
        res = call("get_cart")
        cart = res.get("cart", {})
        if not cart.get("items"):
            return "Your cart is empty right now."
        lines = ", ".join(f"{i['quantity']}x {i['name']}" for i in cart["items"])
        return f"Your cart: {lines}. Total {cart['total']}."

    # default: treat as a product search
    max_price = _parse_price(text)
    tokens = [w for w in text.replace("₹", " ").split() if w not in _FILLER and not w.isdigit()]
    query = " ".join(tokens[:6]) or message
    kw: dict = {"query": query}
    if max_price:
        kw["max_price_rupees"] = max_price / 100
    res = call("search_products", **kw)
    if not res.get("ok") or res.get("count", 0) == 0:
        return f"I couldn't find anything matching '{query}'. Try different words."
    names = ", ".join(p["name"] for p in res["products"][:5])
    cap = f" under ₹{max_price // 100}" if max_price else ""
    return f"Here are {res['count']} options{cap}: {names}. Tap “Add to cart” on any of them."


def run_agent(
    db: Session,
    *,
    session_id: str,
    message: str,
    model=None,
) -> AgentResponse:
    from app.core.exceptions import SessionNotFoundError

    sessions = SessionRepository(db)
    session = sessions.get(session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} was not found.")

    CartService(db).get_cart_for_session(session_id)  # ensure the cart exists
    history = AgentState.load_history(session.chat_history)

    ctx = ToolContext(db=db, session_id=session_id)
    tools = build_tools(ctx)

    from app.core.config import settings

    if model is None and not settings.gemini_configured:
        reply = _run_fallback(ctx, tools, message)
    else:
        if model is None:
            from app.integrations.llm.gemini import get_chat_model

            model = get_chat_model()

        from langchain.agents import create_agent

        from app.core.config import settings as _s

        agent = create_agent(model, tools)
        try:
            lc_result = agent.invoke(
                {"messages": _to_lc_messages(history, message)},
                config={"recursion_limit": _s.agent_max_tool_iterations * 2 + 1},
            )
            reply = _final_text(lc_result)
        except Exception as exc:  # LLM/tool-loop failure -> safe, bounded fallback
            log.warning("agent LLM path failed (%s); using deterministic fallback", exc)
            ctx.invocations.clear()
            reply = _run_fallback(ctx, tools, message)

    actions = _build_actions(ctx)

    # persist chat history
    history.append(ChatTurn(role="user", content=message))
    history.append(ChatTurn(role="assistant", content=reply))
    session.chat_history = AgentState.dump_history(history)
    db.commit()
    db.refresh(session)

    log.info(
        "agent turn session=%s tools=%s", session_id, [i.name for i in ctx.invocations]
    )
    return AgentResponse(
        message=reply,
        state=session.state.value,
        actions=actions,
        tool_calls=[i.name for i in ctx.invocations],
    )
