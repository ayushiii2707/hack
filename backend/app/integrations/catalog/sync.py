"""Catalog synchronization: fetch -> normalize -> validate -> upsert -> audit.

Idempotent: re-running updates existing rows (matched on source+external_id)
rather than creating duplicates.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import AuditAction, AuditActor
from app.integrations.catalog.base import CatalogProvider
from app.integrations.catalog.dummyjson import DummyJSONProvider
from app.integrations.catalog.normalizer import NormalizationError, normalize
from app.repositories.product_repository import ProductRepository
from app.services.audit_service import AuditService
from app.utils.logging import get_logger

log = get_logger("catalog.sync")


@dataclass
class SyncResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deactivated: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "deactivated": self.deactivated,
            "error_count": len(self.errors),
        }


def sync_catalog(
    db: Session,
    *,
    provider: CatalogProvider | None = None,
    limit: int | None = None,
) -> SyncResult:
    provider = provider or DummyJSONProvider()
    limit = limit or settings.catalog_sync_limit
    repo = ProductRepository(db)
    audit = AuditService(db)
    result = SyncResult()

    seen_external_ids: set[str] = set()
    skip = 0
    page_size = min(limit, 100)
    while result.fetched < limit:
        batch = provider.fetch_products(limit=page_size, skip=skip)
        if not batch:
            break
        for raw in batch:
            result.fetched += 1
            try:
                norm = normalize(raw)
            except (NormalizationError, ValueError, ArithmeticError) as exc:
                # A poisoned/garbage row is skipped, never aborts the sync.
                result.skipped += 1
                result.errors.append(f"{raw.external_id}: {exc}"[:200])
                continue
            seen_external_ids.add(norm.external_id)
            _, created = repo.upsert(norm)
            if created:
                result.created += 1
            else:
                result.updated += 1
        skip += len(batch)
        if len(batch) < page_size:
            break

    # A full sweep (we reached the provider's end, no per-run limit truncation)
    # lets us safely deactivate products that vanished from the feed.
    full_sweep = result.fetched < limit or limit >= settings.catalog_sync_limit
    if full_sweep and seen_external_ids:
        result.deactivated = repo.deactivate_missing(provider.source, seen_external_ids)

    db.commit()

    audit.log_event(
        actor=AuditActor.SYSTEM,
        action=AuditAction.CATALOG_SYNCED,
        reason=(
            f"Synced {result.fetched} products from {provider.source}: "
            f"{result.created} created, {result.updated} updated, "
            f"{result.skipped} skipped, {result.deactivated} deactivated"
        ),
        metadata=result.as_dict() | {"source": provider.source},
    )
    db.commit()
    log.info("catalog sync done: %s", result.as_dict())
    return result


def _main() -> None:  # pragma: no cover - CLI entrypoint
    from app.database.database import SessionLocal, create_all

    create_all()
    db = SessionLocal()
    try:
        res = sync_catalog(db)
        print("Catalog sync:", res.as_dict())
        if res.errors:
            print(f"  ({len(res.errors)} normalization errors, first: {res.errors[0]})")
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    _main()
