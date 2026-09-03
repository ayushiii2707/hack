"""One-command project bootstrap.

    python -m app.database.seed

1. create tables
2. sync the catalog from the external provider
3. verify products exist
"""
from __future__ import annotations

import sys

from app.database.database import SessionLocal, create_all
from app.integrations.catalog.sync import sync_catalog
from app.repositories.product_repository import ProductRepository
from app.utils.logging import get_logger

log = get_logger("seed")


def run() -> int:
    log.info("creating tables ...")
    create_all()

    db = SessionLocal()
    try:
        repo = ProductRepository(db)
        existing = repo.count()
        log.info("products currently in DB: %d", existing)

        result = sync_catalog(db)
        log.info("sync result: %s", result.as_dict())

        total = repo.count()
        if total == 0:
            log.error("no products after sync – check CATALOG_BASE_URL / connectivity")
            return 1
        sample = repo.list_all(limit=3)
        for p in sample:
            log.info("  %s | %s | %d paise | stock=%d", p.id, p.name, p.price, p.stock)
        log.info("seed complete: %d products available", total)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
