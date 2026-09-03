"""Payment persistence. One row per attempt – terminal rows are never mutated."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import PaymentStatus
from app.models.payment import Payment

_TERMINAL = (PaymentStatus.CAPTURED, PaymentStatus.FAILED)


class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def next_attempt_number(self, order_id: str) -> int:
        current = self.db.execute(
            select(func.max(Payment.attempt_number)).where(Payment.order_id == order_id)
        ).scalar()
        return (current or 0) + 1

    def create_attempt(
        self,
        *,
        order_id: str,
        method: str = "checkout",
        status: PaymentStatus = PaymentStatus.ATTEMPTED,
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            attempt_number=self.next_attempt_number(order_id),
            method=method,
            status=status,
        )
        self.db.add(payment)
        self.db.flush()
        return payment

    def get(self, payment_id: str) -> Payment | None:
        return self.db.get(Payment, payment_id)

    def get_by_razorpay_payment_id(self, razorpay_payment_id: str) -> Payment | None:
        return self.db.execute(
            select(Payment).where(Payment.razorpay_payment_id == razorpay_payment_id)
        ).scalars().first()

    def get_captured(self, order_id: str) -> Payment | None:
        return self.db.execute(
            select(Payment).where(
                Payment.order_id == order_id, Payment.status == PaymentStatus.CAPTURED
            )
        ).scalars().first()

    def list_for_order(self, order_id: str) -> list[Payment]:
        return list(
            self.db.execute(
                select(Payment)
                .where(Payment.order_id == order_id)
                .order_by(Payment.attempt_number)
            ).scalars()
        )

    def latest_for_order(self, order_id: str) -> Payment | None:
        return self.db.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.attempt_number.desc())
        ).scalars().first()

    def has_captured(self, order_id: str) -> bool:
        return self.get_captured(order_id) is not None

    def finalize(self, payment: Payment, **fields) -> Payment:
        """Set terminal fields on a non-terminal attempt row. Refuses to mutate
        a row that is already CAPTURED/FAILED (attempts are historical)."""
        if payment.status in _TERMINAL:
            raise ValueError(
                f"Payment attempt {payment.id} is already {payment.status.value}; "
                "terminal attempts are immutable."
            )
        for key, value in fields.items():
            setattr(payment, key, value)
        self.db.flush()
        return payment
