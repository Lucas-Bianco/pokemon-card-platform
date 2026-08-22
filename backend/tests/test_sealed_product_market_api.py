"""Phase C: GET /sealed/products/{slug}/market — one catalog product's curated
MSRP vs its live eBay sold-comps median.

Combines the two established patterns: monkeypatch `cardplatform.api.settings`
(to control the listings key, like test_sealed_sold_comps_api) AND override
`get_session` with a seeded catalog session (like test_sealed_catalog_api). The
provider fetch is stubbed so no network is hit. Honest flags mirror
/sealed/sold-comps exactly: no key -> unavailable; key set but 0 comps -> empty;
market_median None (never 0) when no comps; delta None unless BOTH msrp and
market_median are real. Unknown slug -> 404.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.config import Settings
from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.provider import SealedSoldComp
from cardplatform.sealed.seed_data import SEALED_PRODUCTS


def _comp(price=118.0):
    return SealedSoldComp(
        query="Scarlet & Violet Elite Trainer Box",
        listing_id="x",
        price=price,
        currency="USD",
        url="https://ebay.example/x",
        condition="New",
        sold_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        title="Scarlet & Violet ETB",
        source="ebay",
    )


def _stub_fetch(monkeypatch, comps):
    from cardplatform.prices import ebay_listings as mod
    monkeypatch.setattr(
        mod.EbayListingsProvider,
        "fetch_sold_listings_by_query",
        lambda self, query, limit=6: comps,
    )


@pytest.fixture
def seeded(db):
    SealedCatalogService(db).ensure_seed(SEALED_PRODUCTS)
    return db


@pytest.fixture
def client(seeded, monkeypatch, tmp_path):
    monkeypatch.setattr("cardplatform.api.settings", Settings(data_dir=tmp_path, listings_api_key="an-app-id"))
    app.dependency_overrides[get_session] = lambda: seeded
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_market_returns_msrp_vs_median(client, monkeypatch):
    _stub_fetch(monkeypatch, [_comp(38.0), _comp(40.0), _comp(42.0)])
    r = client.get("/sealed/products/scarlet-violet-elite-trainer-box/market")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "scarlet-violet-elite-trainer-box"
    assert body["name"] == "Scarlet & Violet Elite Trainer Box"
    assert body["msrp"] == 39.99
    assert body["msrp_currency"] == "USD"
    # median of [38, 40, 42] is 40.
    assert body["market_median"] == 40.0
    assert body["market_source"] == "ebay"
    assert body["market_source_updated_at"] is None  # sold comps carry no per-sale stamp
    assert body["sold_comps_count"] == 3
    assert body["delta"] == 39.99 - 40.0  # msrp - median
    assert body["unavailable"] is False
    assert body["empty"] is False


def test_market_unavailable_when_no_key(seeded, monkeypatch, tmp_path):
    """No listings key -> honest unavailable (provider returns [] without the
    network); market_median is None, never a fabricated 0."""
    monkeypatch.setattr("cardplatform.api.settings", Settings(data_dir=tmp_path, listings_api_key=None))
    _stub_fetch(monkeypatch, [])
    app.dependency_overrides[get_session] = lambda: seeded
    with TestClient(app) as c:
        r = c.get("/sealed/products/scarlet-violet-elite-trainer-box/market")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] is True
    assert body["empty"] is False
    assert body["market_median"] is None
    assert body["sold_comps_count"] == 0
    # delta is None when market_median is None, even though msrp exists.
    assert body["delta"] is None
    # MSRP still surfaces — it's a catalog fact, independent of the market.
    assert body["msrp"] == 39.99


def test_market_empty_when_key_set_but_no_comps(client, monkeypatch):
    _stub_fetch(monkeypatch, [])
    r = client.get("/sealed/products/scarlet-violet-elite-trainer-box/market")
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] is False
    assert body["empty"] is True
    assert body["market_median"] is None
    assert body["delta"] is None
    assert body["sold_comps_count"] == 0


def test_market_no_msrp_delta_none_even_with_median(client, monkeypatch):
    """A product with no MSRP (booster pack) still shows the market median, but
    delta is None — you can't compute MSRP-vs-market without both halves."""
    _stub_fetch(monkeypatch, [_comp(5.0), _comp(6.0)])
    r = client.get("/sealed/products/base-booster-pack/market")
    assert r.status_code == 200
    body = r.json()
    assert body["msrp"] is None
    assert body["market_median"] == 5.5  # median of [5, 6]
    assert body["delta"] is None  # no MSRP -> no delta, never a fabricated 0


def test_market_unknown_slug_404(client, monkeypatch):
    _stub_fetch(monkeypatch, [])
    assert client.get("/sealed/products/does-not-exist/market").status_code == 404


def test_market_provider_failure_degrades_to_empty(client, monkeypatch):
    """A provider exception degrades to [] (honest empty), never a 5xx — mirrors
    the SealedListingsProvider never-raise discipline."""
    from cardplatform.prices import ebay_listings as mod
    monkeypatch.setattr(
        mod.EbayListingsProvider,
        "fetch_sold_listings_by_query",
        lambda self, query, limit=6: (_ for _ in ()).throw(RuntimeError("ebay down")),
    )
    r = client.get("/sealed/products/scarlet-violet-elite-trainer-box/market")
    assert r.status_code == 200
    body = r.json()
    # Key is set, so unavailable is False; the degraded [] makes empty True.
    assert body["unavailable"] is False
    assert body["empty"] is True
    assert body["market_median"] is None