"""Order persistence."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.constants import OrderStatus
from app.models.order import OPEN_ORDER_STATUSES, Order

_TERMINAL = (OrderStatus.PAID, OrderStatus.CANCELLED)
_OPEN = tuple(s.value for s in OPEN_ORDER_STATUSES)


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
            open_cart_key=cart_id,  # UNIQUE -> at most one open order per cart
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
            .where(Order.cart_id == cart_id, Order.status.in_(tuple(OPEN_ORDER_STATUSES)))
            .order_by(Order.created_at.desc())
        ).scalars().first()

    def get_open_for_session(self, session_id: str) -> Order | None:
        return self.db.execute(
            select(Order)
            .where(Order.session_id == session_id, Order.status.in_(tuple(OPEN_ORDER_STATUSES)))
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
        # Release the "one open order per cart" slot on any terminal transition.
        order.open_cart_key = None if status in _TERMINAL else order.cart_id
        self.db.flush()

    def try_close_open_order(self, order_id: str, new_status: OrderStatus) -> bool:
        """Atomically move an OPEN order to a terminal state. Returns False if
        the order is no longer open (already paid/cancelled by a racing request)."""
        result = self.db.execute(
            update(Order)
            .where(Order.id == order_id, Order.status.in_(_OPEN))
            .values(status=new_status, open_cart_key=None)
        )
        self.db.flush()
        return (result.rowcount or 0) == 1

    def set_razorpay_order_id(self, order: Order, razorpay_order_id: str) -> None:
        order.razorpay_order_id = razorpay_order_id
        self.db.flush()
