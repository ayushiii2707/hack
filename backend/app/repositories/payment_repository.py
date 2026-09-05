"""Payment persistence. One row per attempt – terminal rows are never mutated."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import PaymentStatus
from app.core.exceptions import ConflictError
from app.models.payment import Payment

_TERMINAL = (PaymentStatus.CAPTURED, PaymentStatus.FAILED)
_MAX_ATTEMPT_NUMBER_RETRIES = 8


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
        """Allocate the next attempt row for an order.

        ``next_attempt_number`` is a read (MAX+1), not an atomic counter, so
        two concurrent callers for the SAME order (a double-tap on verify, a
        client retry racing a webhook, two duplicate webhook deliveries) can
        compute the same number and both try to INSERT it. The unique
        constraint on ``(order_id, attempt_number)`` correctly stops the
        collision at the database, but without this retry the loser's
        IntegrityError propagated out of every caller (verify_payment,
        record_client_failure, the webhook handler, ...) as a raw, uncaught
        500 instead of the idempotent response those callers already know how
        to give. Each retry runs in its own SAVEPOINT so only the failed
        INSERT is undone — not whatever the caller had already done earlier in
        this transaction.
        """
        last_error: IntegrityError | None = None
        for _ in range(_MAX_ATTEMPT_NUMBER_RETRIES):
            payment = Payment(
                order_id=order_id,
                attempt_number=self.next_attempt_number(order_id),
                method=method,
                status=status,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(payment)
                    self.db.flush()
                return payment
            except IntegrityError as exc:
                last_error = exc
                continue
        raise ConflictError(
            "Could not allocate a payment attempt right now; please retry."
        ) from last_error

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
