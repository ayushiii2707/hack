import pytest

from app.core.exceptions import ProductInactiveError, ProductNotFoundError
from app.integrations.catalog.base import RawProduct
from app.integrations.catalog.normalizer import NormalizationError, normalize
from app.integrations.catalog.sync import sync_catalog
from app.repositories.product_repository import ProductRepository
from app.services.product_service import ProductService
from tests.factories import FakeCatalogProvider, make_product, sample_catalog


def test_normalizer_converts_price_to_paise():
    raw = RawProduct(source="fake", external_id="1", payload={"id": 1, "title": "X", "price": 10.0})
    norm = normalize(raw)
    assert norm.price == 35000  # 10 * 35.0 * 100
    assert norm.currency == "INR"


def test_normalizer_rejects_missing_price():
    with pytest.raises(NormalizationError):
        normalize(RawProduct(source="fake", external_id="1", payload={"id": 1, "title": "X"}))


def test_normalizer_drops_unsafe_urls():
    raw = RawProduct(source="fake", external_id="1", payload={
        "id": 1, "title": "X", "price": 5.0,
        "images": ["javascript:alert(1)"], "thumbnail": "data:text/html,<script>",
    })
    norm = normalize(raw)
    assert norm.image_url == ""


def test_sync_populates_internal_db_and_skips_bad_rows(db_session):
    provider = FakeCatalogProvider(sample_catalog())
    result = sync_catalog(db_session, provider=provider, limit=100)
    assert result.fetched == 4
    assert result.created == 3
    assert result.skipped == 1
    assert ProductRepository(db_session).count() == 3


def test_sync_is_idempotent(db_session):
    provider = FakeCatalogProvider(sample_catalog())
    sync_catalog(db_session, provider=provider, limit=100)
    second = sync_catalog(db_session, provider=provider, limit=100)
    assert second.created == 0
    assert second.updated == 3
    assert ProductRepository(db_session).count() == 3


def test_sync_updates_price_but_preserves_local_stock(db_session):
    catalog = sample_catalog()
    sync_catalog(db_session, provider=FakeCatalogProvider(catalog), limit=100)
    repo = ProductRepository(db_session)
    prod = repo.get_by_external_id("fake", "101")
    # locally decrement stock (as checkout would)
    repo.try_decrement_stock(prod.id, 5)
    db_session.commit()
    catalog[0]["price"] = 40.0
    catalog[0]["stock"] = 999
    sync_catalog(db_session, provider=FakeCatalogProvider(catalog), limit=100)
    db_session.refresh(prod)
    assert prod.price == 140000  # price synced
    assert prod.stock == 20  # local stock NOT clobbered (25 - 5)


def test_sync_deactivates_products_missing_from_feed(db_session):
    catalog = sample_catalog()
    sync_catalog(db_session, provider=FakeCatalogProvider(catalog), limit=100)
    repo = ProductRepository(db_session)
    gone = repo.get_by_external_id("fake", "101")
    # remove product 101 from the feed
    smaller = [c for c in catalog if c["id"] != 101]
    res = sync_catalog(db_session, provider=FakeCatalogProvider(smaller), limit=100)
    db_session.refresh(gone)
    assert gone.active is False
    assert res.deactivated == 1


def test_search_uses_internal_db_with_filters(db_session):
    sync_catalog(db_session, provider=FakeCatalogProvider(sample_catalog()), limit=100)
    svc = ProductService(db_session)
    results = svc.search_products("running", max_price=300000)
    names = {p.name for p in results}
    assert "Running Socks 3-pack" in names
    assert all("Water Bottle" not in n for n in names)  # out of stock


def test_get_inactive_product_raises(db_session):
    p = make_product(db_session, active=False)
    with pytest.raises(ProductInactiveError):
        ProductService(db_session).get_product(p.id, require_active=True)


def test_get_missing_product_raises(db_session):
    with pytest.raises(ProductNotFoundError):
        ProductService(db_session).get_product("prod_nope")


def test_products_api_is_public(client, db_session):
    sync_catalog(db_session, provider=FakeCatalogProvider(sample_catalog()), limit=100)
    resp = client.get("/products?q=running")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert all(isinstance(item["price"], int) for item in body["items"])


def test_catalog_sync_endpoint_requires_admin(client, admin_headers, monkeypatch):
    assert client.post("/products/sync?limit=1").status_code == 403
    assert client.post("/products/sync?limit=1", headers={"X-Admin-Key": "wrong"}).status_code == 403

    import app.integrations.catalog.sync as syncmod

    monkeypatch.setattr(
        syncmod, "sync_catalog",
        lambda db, **kw: syncmod.SyncResult(fetched=0, created=0, updated=0, skipped=0),
    )
    r = client.post("/products/sync?limit=1", headers=admin_headers)
    assert r.status_code == 200


def test_negative_price_rejected_by_db_constraint(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.product import Product

    db_session.add(Product(external_id="neg", source="fake", name="Bad", price=-1, stock=1))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
