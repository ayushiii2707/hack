"""Application configuration, loaded once from the environment.

All tunable policy knobs (quantity caps, shipping, upsell price cap, rate
limits) live here so they are never hardcoded in business logic.

Secure-by-default: in a non-development ``ENVIRONMENT`` the app refuses to
start unless the security-critical settings are present (see
``Settings.validate_for_environment``), which is invoked from the app lifespan.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when configuration is unsafe for the target environment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- infra ---
    database_url: str = "sqlite:///./checkout_copilot.db"
    app_name: str = "PayPilot"
    environment: str = "development"  # development | staging | production
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trusted_hosts: str = "*"  # comma list; "*" disables host checking (dev only)
    root_path: str = ""  # set when served behind a path-prefixing proxy

    # --- identity / security ---
    # HMAC key used to sign anonymous session tokens. MUST be set (>=32 chars)
    # outside development. A random key is generated for dev if unset.
    session_token_secret: str = ""
    session_token_ttl_hours: int = 72
    # Optional admin key for merchant/ops endpoints (audit-all, catalog sync).
    admin_api_key: str = ""
    # Demo-only endpoints (deterministic payment failure). Off by default.
    enable_demo_endpoints: bool = False
    # Cookie flags (set secure=True behind HTTPS in production).
    session_cookie_name: str = "cc_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"

    # --- external providers ---
    gemini_api_key: str = ""
    # A currently-available Gemini model that supports function calling. Google
    # retires older aliases (e.g. gemini-2.0-flash) — override GEMINI_MODEL if
    # the API returns 404 NOT_FOUND for this one.
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 25.0
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # NOTE: the razorpay SDK's resource classes already prepend "/v1/<resource>"
    # to every request path, so this must be the bare host — NOT ".../v1" (that
    # would double up to ".../v1/v1/orders" and every gateway call would 404).
    razorpay_base_url: str = "https://api.razorpay.com"
    razorpay_timeout_seconds: float = 15.0
    catalog_base_url: str = "https://dummyjson.com"
    catalog_timeout_seconds: float = 15.0

    # --- commerce policy (money values are integer PAISE) ---
    max_item_quantity: int = Field(default=5, ge=1, le=100)
    upsell_price_cap_percent: int = Field(default=20, ge=1, le=100)
    shipping_fee: int = Field(default=500, ge=0)            # paise
    free_shipping_threshold: int = Field(default=200000, ge=0)  # paise
    catalog_sync_limit: int = Field(default=200, ge=1, le=1000)
    agent_product_context_limit: int = Field(default=5, ge=1, le=20)
    agent_max_tool_iterations: int = Field(default=12, ge=1, le=50)
    # DummyJSON prices are small USD-ish floats; multiply to realistic INR.
    catalog_price_multiplier: float = Field(default=35.0, gt=0)

    # --- rate limiting (in-process token bucket; per client IP) ---
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 120
    rate_limit_agent_per_minute: int = 15
    rate_limit_payment_per_minute: int = 20
    rate_limit_session_create_per_minute: int = 20
    rate_limit_webhook_per_minute: int = 300
    rate_limit_search_per_minute: int = 60

    # --- catalog sync behaviour ---
    # When True, catalog sync never overwrites locally-managed stock for
    # products that already exist (stock is authoritative locally once we
    # start decrementing it at checkout).
    catalog_sync_preserve_local_stock: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def is_production_like(self) -> bool:
        return self.environment.lower() in {"production", "staging", "prod"}

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_api_key)

    @model_validator(mode="after")
    def _dev_defaults(self) -> Settings:
        # Provide an ephemeral signing key in development so the app runs
        # out of the box; never do this in production.
        if not self.session_token_secret and not self.is_production_like:
            import secrets

            object.__setattr__(self, "session_token_secret", secrets.token_hex(32))
        return self

    def validate_for_environment(self) -> list[str]:
        """Return a list of fatal configuration problems for this environment."""
        problems: list[str] = []
        if not self.is_production_like:
            return problems
        if len(self.session_token_secret) < 32:
            problems.append("SESSION_TOKEN_SECRET must be set (>=32 chars) in production.")
        if self.razorpay_configured and not self.razorpay_webhook_secret:
            problems.append(
                "RAZORPAY_WEBHOOK_SECRET must be set when Razorpay is configured "
                "(unsigned webhooks are rejected)."
            )
        if self.enable_demo_endpoints:
            problems.append("ENABLE_DEMO_ENDPOINTS must be false in production.")
        if "*" in self.trusted_host_list:
            problems.append("TRUSTED_HOSTS must be an explicit host list in production.")
        if any(o in ("*",) for o in self.cors_origin_list) or not self.cors_origin_list:
            problems.append("CORS_ORIGINS must be an explicit origin list in production.")
        if self.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL points at SQLite; use PostgreSQL for production "
                "(set DATABASE_URL=postgresql+psycopg://...)."
            )
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true in production (HTTPS).")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
