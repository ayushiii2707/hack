"""Gemini LLM factory (via langchain-google-genai)."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.exceptions import AppError


class LLMNotConfiguredError(AppError):
    """The Gemini API key is not configured."""

    code = "LLM_NOT_CONFIGURED"
    status_code = 503


@lru_cache
def get_chat_model():
    if not settings.gemini_configured:
        raise LLMNotConfiguredError("GEMINI_API_KEY is not set on the server.")
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.2,
        max_retries=1,
        timeout=settings.gemini_timeout_seconds,
    )
