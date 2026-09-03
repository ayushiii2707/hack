"""Order persistence."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import OrderStatus
from app.models.order import Order

OPEN_ORDER_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.PAYMENT_PENDING,
    OrderStatus.PAYMENT_FAILED,
)


class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        session_id: str,
        cart_id: str,
        amount: int,
        subtotal: int,
        shipping: int,
        tax: int,
        currency: str,
        receipt: str,
    ) -> Order:
        order = Order(
            session_id=session_id,
            cart_id=cart_id,
            amount=amount,
            subtotal=subtotal,
            shipping=shipping,
            tax=tax,
            currency=currency,
            receipt=receipt,
            status=OrderStatus.CREATED,
        )
        self.db.add(order)
        self.db.flush()
        return order

    def get(self, order_id: str) -> Order | None:
        return self.db.get(Order, order_id)

    def get_by_razorpay_id(self, razorpay_order_id: str) -> Order | None:
        return self.db.execute(
            select(Order).where(Order.razorpay_order_id == razorpay_order_id)
        ).scalar_one_or_none()

    def get_open_for_cart(self, cart_id: str) -> Order | None:
        return self.db.execute(
            select(Order)
            .where(Order.cart_id == cart_id, Order.status.in_(OPEN_ORDER_STATUSES))
            .order_by(Order.created_at.desc())
        ).scalars().first()

    def latest_for_session(self, session_id: str) -> Order | None:
        return self.db.execute(
            select(Order)
            .where(Order.session_id == session_id)
            .order_by(Order.created_at.desc())
        ).scalars().first()

    def set_status(self, order: Order, status: OrderStatus) -> None:
        order.status = status
        self.db.flush()

    def set_razorpay_order_id(self, order: Order, razorpay_order_id: str) -> None:
        order.razorpay_order_id = razorpay_order_id
        self.db.flush()
