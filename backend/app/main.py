"""FastAPI application entrypoint.

Deliberately boring: create the app, wire middleware + exception handlers,
register the router, validate config, create tables (dev) on startup.
No business logic here.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.core.config import ConfigError, settings
from app.core.context import set_context_session_id, set_request_id
from app.core.exceptions import AppError
from app.core.ratelimit import bucket_for_path, limiter
from app.database.database import create_all
from app.utils.logging import get_logger

log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = settings.validate_for_environment()
    if problems:
        for p in problems:
            log.error("CONFIG: %s", p)
        raise ConfigError(
            f"Refusing to start in environment '{settings.environment}': "
            + "; ".join(problems)
        )
    if settings.database_url.startswith("sqlite"):
        create_all()  # dev/test convenience; production uses Alembic migrations
    log.info("%s started (env=%s)", settings.app_name, settings.environment)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.1.0",
    description=(
        "Conversational checkout agent. The LLM orchestrates conversation; the "
        "deterministic backend is the sole authority for pricing, checkout and payments."
    ),
    lifespan=lifespan,
    root_path=settings.root_path,
)

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        set_request_id(rid)
        set_context_session_id(None)
        try:
            response = await call_next(request)
        finally:
            set_request_id(None)
            set_context_session_id(None)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production_like:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in (
            "/health", "/health/ready", "/", "/docs", "/openapi.json", "/redoc"
        ):
            return await call_next(request)
        # request.client.host is set from X-Forwarded-For by uvicorn only when
        # started with --proxy-headers --forwarded-allow-ips=<proxy>, so it is
        # not spoofable from an untrusted client.
        ip = request.client.host if request.client else "unknown"
        bucket, per_min = bucket_for_path(request.method, request.url.path)
        allowed, retry_after = limiter.check(key=ip, bucket=bucket, per_minute=per_min)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "Too many requests."}},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


# add_middleware prepends, so the LAST call is the OUTERMOST layer.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Request-ID"],
)
if "*" not in settings.trusted_host_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


@app.exception_handler(AppError)
async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.details or None),
    )


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Return only the location + message, never the submitted input values.
    safe = [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_body("VALIDATION_ERROR", "Request validation failed", {"errors": safe}),
    )


@app.exception_handler(Exception)
async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    log.exception("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=_error_body("INTERNAL_ERROR", "An unexpected error occurred."),
    )


app.include_router(api_router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "health": "/health"}
