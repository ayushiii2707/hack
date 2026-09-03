"""FastAPI application entrypoint.

Deliberately boring: create the app, wire middleware + exception handlers,
register the router, create tables on startup. No business logic here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.database.database import create_all
from app.utils.logging import get_logger

log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_all()
    log.info("%s started (env=%s)", settings.app_name, settings.environment)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Conversational checkout agent. The LLM orchestrates conversation; the "
        "deterministic backend remains the authority for pricing, checkout and payments."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return JSONResponse(
        status_code=422,
        content=_error_body("VALIDATION_ERROR", "Request validation failed", {"errors": exc.errors()}),
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
