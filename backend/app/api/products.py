"""Product APIs. Runtime reads hit the internal DB, never DummyJSON directly."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.database.database import get_db
from app.schemas.product import CatalogSyncOut, ProductListOut, ProductOut
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


def _svc(db: Session = Depends(get_db)) -> ProductService:
    return ProductService(db)


@router.get("", response_model=ProductListOut, summary="List / filter products")
def list_products(
    svc: ProductService = Depends(_svc),
    q: str | None = Query(None, description="Free-text query"),
    category: str | None = None,
    min_price: int | None = Query(None, description="Min price in paise"),
    max_price: int | None = Query(None, description="Max price in paise"),
    limit: int = Query(20, ge=1, le=100),
):
    items = svc.search_products(
        q, category=category, min_price=min_price, max_price=max_price, limit=limit
    )
    return ProductListOut(items=[ProductOut.from_model(p) for p in items], count=len(items))


@router.get("/search", response_model=ProductListOut, summary="Search products")
def search_products(
    svc: ProductService = Depends(_svc),
    q: str = Query(..., min_length=1),
    min_price: int | None = None,
    max_price: int | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    items = svc.search_products(q, min_price=min_price, max_price=max_price, limit=limit)
    return ProductListOut(items=[ProductOut.from_model(p) for p in items], count=len(items))


@router.get("/categories", response_model=list[str], summary="Distinct categories")
def list_categories(svc: ProductService = Depends(_svc)):
    return svc.list_categories()


@router.get("/category/{category}", response_model=ProductListOut)
def by_category(category: str, svc: ProductService = Depends(_svc), limit: int = Query(50, ge=1, le=100)):
    items = svc.get_products_by_category(category, limit=limit)
    return ProductListOut(items=[ProductOut.from_model(p) for p in items], count=len(items))


@router.get("/{product_id}", response_model=ProductOut, summary="Get one product")
def get_product(product_id: str, svc: ProductService = Depends(_svc)):
    return ProductOut.from_model(svc.get_product(product_id, require_active=False))


@router.post(
    "/sync",
    response_model=CatalogSyncOut,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    summary="Trigger catalog sync from the external provider (admin, idempotent)",
)
def trigger_sync(db: Session = Depends(get_db), limit: int | None = Query(None, ge=1, le=500)):
    from app.integrations.catalog.sync import sync_catalog

    res = sync_catalog(db, limit=limit)
    return CatalogSyncOut(**res.as_dict())
