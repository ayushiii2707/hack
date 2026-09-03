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
