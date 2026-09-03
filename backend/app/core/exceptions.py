"""Domain exceptions.

Every exception carries a stable ``code`` (for the structured API error body)
and a default HTTP ``status_code``. The API layer has a single handler that
turns any :class:`AppError` into ``{"error": {"code", "message"}}``.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected, client-facing domain errors."""

    code: str = "APP_ERROR"
    status_code: int = 400

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        self.message = message or self.__class__.__doc__ or self.code
        self.details = details or {}
        super().__init__(self.message)


# --- catalog / product ---
class ProductNotFoundError(AppError):
    """The requested product does not exist."""

    code = "PRODUCT_NOT_FOUND"
    status_code = 404


class ProductInactiveError(AppError):
    """This product is not currently available for purchase."""

    code = "PRODUCT_INACTIVE"
    status_code = 409


class InsufficientStockError(AppError):
    """There is not enough stock to satisfy the requested quantity."""

    code = "INSUFFICIENT_STOCK"
    status_code = 409


class InvalidQuantityError(AppError):
    """The requested quantity is not valid."""

    code = "INVALID_QUANTITY"
    status_code = 422


# --- cart / checkout ---
class EmptyCartError(AppError):
    """The cart is empty."""

    code = "EMPTY_CART"
    status_code = 409


class CartNotFoundError(AppError):
    """The requested cart does not exist."""

    code = "CART_NOT_FOUND"
    status_code = 404


class CheckoutValidationError(AppError):
    """The cart cannot proceed to checkout in its current state."""

    code = "CHECKOUT_VALIDATION_FAILED"
    status_code = 409


class OrderNotFoundError(AppError):
    """The requested order does not exist."""

    code = "ORDER_NOT_FOUND"
    status_code = 404


class SessionNotFoundError(AppError):
    """The requested session does not exist."""

    code = "SESSION_NOT_FOUND"
    status_code = 404


class InvalidStateTransitionError(AppError):
    """The requested session state transition is not allowed."""

    code = "INVALID_STATE_TRANSITION"
    status_code = 409


# --- upsell ---
class UpsellAlreadyShownError(AppError):
    """An upsell has already been shown in this session; only one is allowed."""

    code = "UPSELL_ALREADY_SHOWN"
    status_code = 409


class UpsellNotAvailableError(AppError):
    """No suitable upsell candidate is available for this cart."""

    code = "UPSELL_NOT_AVAILABLE"
    status_code = 404


# --- payment ---
class PaymentError(AppError):
    """The payment could not be processed."""

    code = "PAYMENT_ERROR"
    status_code = 402


class RazorpayError(AppError):
    """The payment provider returned an error."""

    code = "RAZORPAY_ERROR"
    status_code = 502


class PaymentVerificationError(AppError):
    """The payment could not be verified and will not be marked as paid."""

    code = "PAYMENT_VERIFICATION_FAILED"
    status_code = 400


# --- policy ---
class PolicyViolationError(AppError):
    """This action is blocked by a backend policy."""

    code = "POLICY_VIOLATION"
    status_code = 403


class ExternalProviderError(AppError):
    """An external data provider failed."""

    code = "EXTERNAL_PROVIDER_ERROR"
    status_code = 502


# --- auth / abuse ---
class AuthenticationError(AppError):
    """A valid session credential is required."""

    code = "AUTHENTICATION_REQUIRED"
    status_code = 401


class ForbiddenError(AppError):
    """You do not have access to this resource."""

    code = "FORBIDDEN"
    status_code = 403


class RateLimitedError(AppError):
    """Too many requests. Slow down."""

    code = "RATE_LIMITED"
    status_code = 429


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    code = "CONFLICT"
    status_code = 409


class LLMUnavailableError(AppError):
    """The conversational model is not available."""

    code = "LLM_UNAVAILABLE"
    status_code = 503
