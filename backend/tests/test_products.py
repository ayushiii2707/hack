import pytest

from app.core.exceptions import ProductInactiveError, ProductNotFoundError
from app.integrations.catalog.normalizer import NormalizationError, normalize
from app.integrations.catalog.base import RawProduct
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


def test_sync_populates_internal_db_and_skips_bad_rows(db_session):
    provider = FakeCatalogProvider(sample_catalog())
    result = sync_catalog(db_session, provider=provider, limit=100)
    assert result.fetched == 4
    assert result.created == 3
    assert result.skipped == 1  # the broken (price=None) row
    assert ProductRepository(db_session).count() == 3


def test_sync_is_idempotent(db_session):
    provider = FakeCatalogProvider(sample_catalog())
    sync_catalog(db_session, provider=provider, limit=100)
    second = sync_catalog(db_session, provider=provider, limit=100)
    assert second.created == 0
    assert second.updated == 3
    assert ProductRepository(db_session).count() == 3


def test_sync_updates_price_on_change(db_session):
    catalog = sample_catalog()
    provider = FakeCatalogProvider(catalog)
    sync_catalog(db_session, provider=provider, limit=100)
    catalog[0]["price"] = 40.0
    sync_catalog(db_session, provider=FakeCatalogProvider(catalog), limit=100)
    repo = ProductRepository(db_session)
    prod = repo.get_by_external_id("fake", "101")
    assert prod.price == 140000  # 40 * 35 * 100


def test_search_uses_internal_db_with_filters(db_session):
    sync_catalog(db_session, provider=FakeCatalogProvider(sample_catalog()), limit=100)
    svc = ProductService(db_session)
    results = svc.search_products("running", max_price=300000)
    names = {p.name for p in results}
    assert "Running Socks 3-pack" in names
    # Water bottle is out of stock -> excluded
    assert all("Water Bottle" not in n for n in names)


def test_get_inactive_product_raises(db_session):
    p = make_product(db_session, active=False)
    svc = ProductService(db_session)
    with pytest.raises(ProductInactiveError):
        svc.get_product(p.id, require_active=True)


def test_get_missing_product_raises(db_session):
    with pytest.raises(ProductNotFoundError):
        ProductService(db_session).get_product("prod_nope")


def test_products_api_list(client, db_session):
    sync_catalog(db_session, provider=FakeCatalogProvider(sample_catalog()), limit=100)
    resp = client.get("/products?q=running")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert all("price" in item and isinstance(item["price"], int) for item in body["items"])
