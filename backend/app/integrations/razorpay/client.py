"""Razorpay client wrapper.

Thin seam over the official ``razorpay`` SDK: centralises auth, error
translation and signature verification, and gives tests one place to inject a
fake. Credentials come only from settings (env), never hardcoded.
"""
from __future__ import annotations

from typing import Any

import razorpay
from razorpay.errors import (
    BadRequestError,
    GatewayError,
    ServerError,
    SignatureVerificationError,
)

from app.core.config import settings
from app.core.exceptions import PaymentVerificationError, RazorpayError
from app.utils.logging import get_logger

log = get_logger("razorpay")


class RazorpayClient:
    def __init__(self, key_id: str | None = None, key_secret: str | None = None):
        self.key_id = key_id or settings.razorpay_key_id
        self.key_secret = key_secret or settings.razorpay_key_secret
        if not (self.key_id and self.key_secret):
            raise RazorpayError("Razorpay is not configured (missing key id/secret).")
        self._sdk = razorpay.Client(auth=(self.key_id, self.key_secret))
        self._sdk.set_app_details({"title": settings.app_name, "version": "1.0.0"})

    # ---- orders ----
    def create_order(self, *, amount: int, currency: str, receipt: str, notes: dict | None = None) -> dict:
        try:
            return self._sdk.order.create(
                {
                    "amount": int(amount),
                    "currency": currency,
                    "receipt": receipt,
                    "payment_capture": 1,
                    "notes": notes or {},
                }
            )
        except (BadRequestError, GatewayError, ServerError) as exc:
            log.error("razorpay order.create failed: %s", exc)
            raise RazorpayError(f"Could not create payment order: {exc}") from exc

    def fetch_order(self, razorpay_order_id: str) -> dict:
        try:
            return self._sdk.order.fetch(razorpay_order_id)
        except (BadRequestError, GatewayError, ServerError) as exc:
            raise RazorpayError(f"Could not fetch order: {exc}") from exc

    # ---- payments ----
    def fetch_payment(self, razorpay_payment_id: str) -> dict:
        try:
            return self._sdk.payment.fetch(razorpay_payment_id)
        except (BadRequestError, GatewayError, ServerError) as exc:
            raise RazorpayError(f"Could not fetch payment: {exc}") from exc

    # ---- payment links ----
    def create_payment_link(self, payload: dict[str, Any]) -> dict:
        try:
            return self._sdk.payment_link.create(payload)
        except (BadRequestError, GatewayError, ServerError) as exc:
            log.error("razorpay payment_link.create failed: %s", exc)
            raise RazorpayError(f"Could not create payment link: {exc}") from exc

    # ---- signature verification ----
    def verify_payment_signature(
        self, *, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
    ) -> None:
        try:
            self._sdk.utility.verify_payment_signature(
                {
                    "razorpay_order_id": razorpay_order_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_signature": razorpay_signature,
                }
            )
        except SignatureVerificationError as exc:
            raise PaymentVerificationError("Payment signature verification failed.") from exc

    def verify_webhook_signature(self, *, body: str, signature: str) -> None:
        secret = settings.razorpay_webhook_secret
        if not secret:
            raise PaymentVerificationError("Webhook secret is not configured.")
        try:
            self._sdk.utility.verify_webhook_signature(body, signature, secret)
        except SignatureVerificationError as exc:
            raise PaymentVerificationError("Webhook signature verification failed.") from exc


def get_razorpay_client() -> RazorpayClient:
    return RazorpayClient()
