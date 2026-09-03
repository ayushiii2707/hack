"""Payment API schemas. The backend never accepts an amount from the client."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.payment import Payment
from app.utils.money import format_inr
from app.utils.time import isoformat


class PaymentInitOut(BaseModel):
    key_id: str
    razorpay_order_id: str
    order_id: str
    amount: int
    amount_display: str
    currency: str
    name: str
    description: str
    notes: dict

    @classmethod
    def from_init(cls, data: dict) -> "PaymentInitOut":
        return cls(amount_display=format_inr(data["amount"]), **data)


class CreatePaymentOrderIn(BaseModel):
    order_id: str = Field(min_length=1)


class VerifyPaymentIn(BaseModel):
    order_id: str = Field(min_length=1)
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


class PaymentFailedIn(BaseModel):
    order_id: str = Field(min_length=1)
    razorpay_payment_id: str | None = None
    reason: str = "Payment failed at the gateway."
    error_code: str | None = None


class PaymentLinkIn(BaseModel):
    order_id: str = Field(min_length=1)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_contact: str | None = None


class VerifyResultOut(BaseModel):
    success: bool
    order_status: str
    payment_status: str
    attempt_number: int
    message: str


class PaymentAttemptOut(BaseModel):
    id: str
    attempt_number: int
    method: str
    status: str
    razorpay_payment_id: str | None
    razorpay_payment_link_id: str | None
    payment_link_url: str | None
    failure_reason: str | None
    created_at: str | None

    @classmethod
    def from_model(cls, p: Payment) -> "PaymentAttemptOut":
        return cls(
            id=p.id,
            attempt_number=p.attempt_number,
            method=p.method,
            status=p.status.value,
            razorpay_payment_id=p.razorpay_payment_id,
            razorpay_payment_link_id=p.razorpay_payment_link_id,
            payment_link_url=p.payment_link_url,
            failure_reason=p.failure_reason,
            created_at=isoformat(p.created_at),
        )


class PaymentLinkOut(BaseModel):
    payment_link_id: str
    short_url: str | None
    amount: int
    currency: str
    reused: bool
