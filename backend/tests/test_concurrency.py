"""Concurrency: the one-shot upsell, single-open-order and stock reservation
guarantees must hold when many requests race, not just sequentially.

Uses a file-backed SQLite database (WAL) with a real connection pool so
separate threads get separate connections.
"""
from __future__ import annotations

import concurrent.futures as cf

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.constants import OrderStatus
from app.models.base import Base
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.session_repository import SessionRepository
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.session_service import SessionService
from app.services.upsell_service import UpsellService
from tests.factories import make_product


@pytest.fixture()
def Sf(tmp_path):
    url = f"sqlite:///{tmp_path/'conc.db'}"
    engine = create_engine(url, future=True, connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi, _):
        cur = dbapi.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    engine.dispose()


def _run(n, fn):
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        return [f.result() for f in [ex.submit(fn, i) for i in range(n)]]


def test_one_shot_upsell_holds_under_concurrency(Sf):
    with Sf() as s:
        issued = SessionService(s).create_session()
        sid = issued.session.id
        cart_id = issued.session.cart.id
        anchor = make_product(s, external_id="a", name="Shoes", category="mens-shoes",
                              price=280000, stock=50, tags=["running"])
        make_product(s, external_id="b", name="Socks", category="mens-shoes",
                     price=15000, stock=50, tags=["running", "socks"])
        CartService(s).add_item(cart_id, anchor.id, 1)

    def claim(_):
        with Sf() as s:
            return SessionRepository(s).try_claim_upsell(sid) and (s.commit() or True)

    winners = [w for w in _run(16, claim) if w]
    assert len(winners) == 1

    with Sf() as s:
        from app.models.session import Session

        assert s.get(Session, sid).upsell_shown is True


def test_generate_recommendation_concurrent_yields_one_shown(Sf):
    with Sf() as s:
        issued = SessionService(s).create_session()
        sid = issued.session.id
        cart_id = issued.session.cart.id
        anchor = make_product(s, external_id="a", name="Shoes", category="mens-shoes",
                              price=280000, stock=50, tags=["running"])
        make_product(s, external_id="b", name="Socks", category="mens-shoes",
                     price=15000, stock=50, tags=["running", "socks"])
        CartService(s).add_item(cart_id, anchor.id, 1)

    def gen(_):
        with Sf() as s:
            try:
                UpsellService(s).generate_recommendation(sid)
                return "shown"
            except Exception as e:
                return type(e).__name__

    results = _run(12, gen)
    assert results.count("shown") == 1

    with Sf() as s:
        from app.core.constants import AuditAction
        from app.models.audit_log import AuditLog

        count = s.query(AuditLog).filter(AuditLog.action == AuditAction.UPSELL_SHOWN).count()
        assert count == 1


def test_concurrent_checkout_confirm_creates_one_order(Sf):
    with Sf() as s:
        issued = SessionService(s).create_session()
        sid = issued.session.id
        p = make_product(s, price=100000, stock=100)
        CartService(s).add_item(issued.session.cart.id, p.id, 1)

    def confirm(_):
        with Sf() as s:
            try:
                return CheckoutService(s).confirm_checkout(sid).id
            except Exception as e:
                return type(e).__name__

    ids = {r for r in _run(10, confirm) if r and r.startswith("ord_")}
    assert len(ids) == 1

    with Sf() as s:
        from app.models.order import Order

        open_orders = s.query(Order).filter(Order.open_cart_key.isnot(None)).count()
        assert open_orders == 1


def test_no_oversell_when_many_buyers_race_for_last_unit(Sf):
    with Sf() as s:
        p = make_product(s, price=100000, stock=3)
        pid = p.id
        sessions = []
        for _ in range(10):
            issued = SessionService(s).create_session()
            CartService(s).add_item(issued.session.cart.id, pid, 1)
            sessions.append(issued.session.id)

    def buy(i):
        with Sf() as s:
            try:
                CheckoutService(s).confirm_checkout(sessions[i])
                return True
            except Exception:
                return False

    ok = [x for x in _run(10, buy) if x]
    assert len(ok) == 3  # exactly the available stock

    with Sf() as s:
        assert ProductRepository(s).get_by_id(pid).stock == 0


def test_cancel_vs_verify_race_never_leaves_inconsistent_state(Sf):
    """A cancel racing a payment verification must resolve to exactly one of:
      * PAID  -> stock stays reserved, capture recorded
      * CANCELLED -> stock released; if a capture happened it is flagged for
        manual reconciliation (never silently kept AND released)."""
    import sys

    sys.path.insert(0, "tests")
    from factories import FakeRazorpayClient

    from app.core.constants import PaymentStatus
    from app.models.audit_log import AuditLog
    from app.models.payment import Payment
    from app.models.product import Product
    from app.services.payment_service import PaymentService

    fake = FakeRazorpayClient()
    seen = {"PAID": 0, "CANCELLED": 0}
    for trial in range(12):
        with Sf() as s:
            sid = SessionService(s).create_session().session.id
            p = make_product(s, external_id=f"r{trial}", price=250000, stock=10)
            pid = p.id
            CartService(s).add_item(SessionService(s).get_session(sid).cart.id, pid, 1)
            oid = CheckoutService(s).confirm_checkout(sid).id
            rzp = PaymentService(s, client=fake).ensure_payment_order(
                CheckoutService(s).get_order(oid)
            )["razorpay_order_id"]
        rpid, sig = fake.simulate_success(rzp)

        def verify():
            with Sf() as s:
                try:
                    PaymentService(s, client=fake).verify_payment(
                        order=CheckoutService(s).get_order(oid),
                        razorpay_order_id=rzp, razorpay_payment_id=rpid, razorpay_signature=sig)
                except Exception:
                    pass

        def cancel():
            with Sf() as s:
                try:
                    CheckoutService(s).cancel_checkout(sid)
                except Exception:
                    pass

        with cf.ThreadPoolExecutor(2) as ex:
            [f.result() for f in (ex.submit(verify), ex.submit(cancel))]

        with Sf() as s:
            o = CheckoutService(s).get_order(oid)
            caps = s.query(Payment).filter_by(order_id=oid, status=PaymentStatus.CAPTURED).count()
            stock = s.get(Product, pid).stock
            flagged = s.query(AuditLog).filter(
                AuditLog.order_id == oid, AuditLog.action == "PAYMENT_VERIFICATION_FAILED"
            ).count()
        seen[o.status.value] += 1
        if o.status.value == "PAID":
            assert caps == 1 and stock == 9
        else:
            assert o.status.value == "CANCELLED" and stock == 10
            if caps == 1:
                assert flagged >= 1  # capture-on-cancelled MUST be flagged
    assert seen["PAID"] + seen["CANCELLED"] == 12


def test_stock_restored_on_cancel_under_concurrency(Sf):
    with Sf() as s:
        p = make_product(s, price=100000, stock=5)
        pid = p.id
        issued = SessionService(s).create_session()
        sid = issued.session.id
        CartService(s).add_item(issued.session.cart.id, pid, 2)
        CheckoutService(s).confirm_checkout(sid)
        assert ProductRepository(s).get_by_id(pid).stock == 3
    with Sf() as s:
        CheckoutService(s).cancel_checkout(sid)
        assert ProductRepository(s).get_by_id(pid).stock == 5


def test_concurrent_adds_to_the_same_line_never_lose_an_increment(Sf, monkeypatch):
    """A live QC pass caught this: 10 threads each POSTing +1 of the SAME
    product to the SAME cart used to collapse to a final quantity of 1, not
    10 -- every thread read the line's starting quantity, computed its own
    "+1" in Python, and the last UPDATE to commit clobbered the rest. The fix
    (CartRepository.try_bump_quantity) makes the increment happen inside the
    UPDATE itself, so no reader ever works from a stale value."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_item_quantity", 100)  # isolate from the cap
    with Sf() as s:
        p = make_product(s, price=100000, stock=1000)
        pid = p.id
        issued = SessionService(s).create_session()
        sid = issued.session.id
        cart_id = issued.session.cart.id

    def add_one(_):
        with Sf() as s:
            CartService(s).add_item(cart_id, pid, 1)

    _run(10, add_one)

    with Sf() as s:
        cart = SessionService(s).get_session(sid).cart
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 10


def test_concurrent_first_adds_of_a_new_line_never_lose_an_increment(Sf, monkeypatch):
    """Same race, but for the INSERT path: 10 threads add a product that is
    NOT yet in the cart at the same time. Exactly one INSERT should win the
    unique-constraint race; the other nine must fall back to bumping the row
    that now exists, not silently drop their quantity or crash."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_item_quantity", 100)  # isolate from the cap
    with Sf() as s:
        p = make_product(s, price=100000, stock=1000)
        pid = p.id
        issued = SessionService(s).create_session()
        sid = issued.session.id
        cart_id = issued.session.cart.id

    def add_one(_):
        with Sf() as s:
            CartService(s).add_item(cart_id, pid, 1)

    _run(10, add_one)

    with Sf() as s:
        cart = SessionService(s).get_session(sid).cart
        assert len(cart.items) == 1  # no duplicate rows for the same product
        assert cart.items[0].quantity == 10


def test_concurrent_adds_past_the_cap_reject_the_overflow_not_lose_it(Sf):
    """The cap (default max_item_quantity=5) must still hold exactly under
    concurrency: with 10 threads racing to add +1 each, exactly 5 succeed and
    the rest get a real PolicyViolationError -- never a silently-lost
    increment AND never a cart that ends up over the cap."""
    from app.core.exceptions import PolicyViolationError

    with Sf() as s:
        p = make_product(s, price=100000, stock=1000)
        pid = p.id
        issued = SessionService(s).create_session()
        sid = issued.session.id
        cart_id = issued.session.cart.id

    def add_one(_):
        with Sf() as s:
            try:
                CartService(s).add_item(cart_id, pid, 1)
                return True
            except PolicyViolationError:
                return False

    results = _run(10, add_one)
    with Sf() as s:
        cart = SessionService(s).get_session(sid).cart
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 5  # the configured max_item_quantity
        assert results.count(True) == 5
        assert results.count(False) == 5


def test_concurrent_identical_verify_calls_never_500_on_attempt_number_race(Sf):
    """A live QC pass caught this: PaymentRepository.create_attempt allocates
    an attempt_number with a plain read (MAX+1) then INSERT -- two concurrent
    callers for the same order can compute the same number and race to insert
    it. The unique constraint on (order_id, attempt_number) correctly stops
    the collision at the database, but the loser's IntegrityError used to
    propagate out of verify_payment as a raw, uncaught 500 instead of the
    idempotent "already verified" response every caller here is entitled to.
    """
    import sys

    sys.path.insert(0, "tests")
    from factories import FakeRazorpayClient

    from app.services.payment_service import PaymentService

    fake = FakeRazorpayClient()
    with Sf() as s:
        p = make_product(s, price=250000, stock=10)
        pid = p.id
        sid = SessionService(s).create_session().session.id
        CartService(s).add_item(SessionService(s).get_session(sid).cart.id, pid, 1)
        oid = CheckoutService(s).confirm_checkout(sid).id
        rzp_order_id = PaymentService(s, client=fake).ensure_payment_order(
            CheckoutService(s).get_order(oid)
        )["razorpay_order_id"]
    payment_id, sig = fake.simulate_success(rzp_order_id)

    def verify(_):
        with Sf() as s:
            result = PaymentService(s, client=fake).verify_payment(
                order=CheckoutService(s).get_order(oid),
                razorpay_order_id=rzp_order_id, razorpay_payment_id=payment_id,
                razorpay_signature=sig,
            )
            return result.success

    results = _run(10, verify)
    assert all(results), results  # no exception escaped to a caller; every reply is success
    with Sf() as s:
        from app.core.constants import PaymentStatus
        from app.models.payment import Payment

        rows = s.query(Payment).filter_by(order_id=oid).all()
        caps = [r for r in rows if r.status == PaymentStatus.CAPTURED]
        assert len(caps) == 1  # still exactly one CAPTURED row despite the race
        # and no half-finished ATTEMPTED rows left behind by a losing thread
        assert all(r.status in (PaymentStatus.CAPTURED, PaymentStatus.FAILED) for r in rows), \
            [(r.attempt_number, r.status.value) for r in rows]
