"""Aggregate API router. Sub-routers are registered here as each phase lands."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    agent,
    audit,
    cart,
    checkout,
    health,
    payments,
    products,
    sessions,
    upsell,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(sessions.router)
api_router.include_router(products.router)
api_router.include_router(cart.router)
api_router.include_router(upsell.router)
api_router.include_router(checkout.router)
api_router.include_router(payments.router)
api_router.include_router(webhooks.router)
api_router.include_router(agent.router)
api_router.include_router(audit.router)
