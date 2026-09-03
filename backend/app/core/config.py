"""Application configuration, loaded once from the environment.

All tunable policy knobs (quantity caps, shipping, upsell price cap) live
here so they are never hardcoded in business logic.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- infra ---
    database_url: str = "sqlite:///./checkout_copilot.db"
    app_name: str = "Checkout Copilot"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- external providers ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_base_url: str = "https://api.razorpay.com/v1"
    catalog_base_url: str = "https://dummyjson.com"

    # --- commerce policy ---
    # NOTE: every money-shaped value below is stored and compared in integer paise.
    max_item_quantity: int = 5
    upsell_price_cap_percent: int = 20
    shipping_fee: int = 500  # paise (₹5 flat shipping)
    free_shipping_threshold: int = 200000  # paise (free over ₹2000)
    catalog_sync_limit: int = 100
    agent_product_context_limit: int = 5
    # DummyJSON prices are small USD-ish floats; multiply to get realistic INR.
    catalog_price_multiplier: float = 83.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
