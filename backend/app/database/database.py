"""Database engine, session factory and FastAPI dependency.

SQLite is supported for local development; PostgreSQL is the production target
(swap ``DATABASE_URL`` — no other change here). For SQLite we enable WAL and a
busy timeout so concurrent readers/writers don't immediately error, and the FK
pragma so ``ondelete`` is honoured.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.base import Base

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {"future": True, "pool_pre_ping": True}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _):  # pragma: no cover - trivial
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_all() -> None:
    """Create every table (dev/test convenience; production uses Alembic)."""
    import app.models  # noqa: F401  (populates Base.metadata)

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
