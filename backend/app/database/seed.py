"""One-command project bootstrap.

    python -m app.database.seed

1. bring the schema up to date (Alembic for real DBs, create_all for SQLite dev)
2. sync the catalog from the external provider
3. verify products exist
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.database.database import SessionLocal, create_all
from app.integrations.catalog.sync import sync_catalog
from app.repositories.product_repository import ProductRepository
from app.utils.logging import get_logger

log = get_logger("seed")


def _migrate() -> None:
    if settings.database_url.startswith("sqlite"):
        log.info("creating tables (SQLite dev) ...")
        create_all()
        return
    log.info("running alembic upgrade head ...")
    root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True)


def run() -> int:
    _migrate()
    db = SessionLocal()
    try:
        repo = ProductRepository(db)
        log.info("products currently in DB: %d", repo.count())
        result = sync_catalog(db)
        log.info("sync result: %s", result.as_dict())
        total = repo.count()
        if total == 0:
            log.error("no products after sync – check CATALOG_BASE_URL / connectivity")
            return 1
        for p in repo.list_all(limit=3):
            log.info("  %s | %s | %d paise | stock=%d", p.id, p.name, p.price, p.stock)
        log.info("seed complete: %d products available", total)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
