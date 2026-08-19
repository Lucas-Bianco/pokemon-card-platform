"""Tests for GET /sealed/deals (Phase 05c)."""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from cardplatform.api import create_app
from cardplatform.config import Settings
from cardplatform.sealed.engine import (
    SealedDealAssessment,
    SealedDealResult,
    SealedPricePoint,
    SealedThresholds,
)


def _stub_result(query="scarlet violet booster box", listings=1, comps=3, market=120.0):
    assessments = [
        SealedDealAssessment(
            query=query,
            listing_id=f"L{i}",
            title=f"L{i}",
            listing_price=100.0,
            currency="USD",
            url=f"u{i}",
            condition="New",
            listing_type="fixed_price",
            auction_end_at=None,
            fetched_at=datetime(2026, 8, 19),
            sealed_market=(
                SealedPricePoint(market, "ebay", None) if market is not None else None
            ),
            flip_edge=(market - 100.0) if market is not None else None,
            deal_score=(market - 100.0) if market is not None else None,
            is_flip=False,
            thresholds=SealedThresholds(20.0, 0.05),
        )
        for i in range(listings)
    ]
    return SealedDealResult(
        query=query,
        assessments=assessments,
        listings_count=listings,
        comps_count=comps,
        sealed_market=(
            SealedPricePoint(market, "ebay", None) if market is not None else None
        ),
        thresholds=SealedThresholds(20.0, 0.05),
    )


def _client(monkeypatch, result=None, key="app-id"):
    app = create_app()
    # Real Settings instance (not a shim) so the schema can't drift silently.
    monkeypatch.setattr(
        "cardplatform.api.settings",
        Settings(
            listings_api_key=key,
            sealed_flip_min_abs=20.0,
            sealed_flip_min_pct=0.05,
            sealed_sold_comp_limit=10,
        ),
    )
    # Replace the engine's assess with a stub so no network is hit.
    if result is None:
        # No key -> provider returns [] without a network call, so the engine
        # produces 0 listings / 0 comps (honest empty, not a fabricated deal).
        if key is None:
            result = _stub_result(query="unused", listings=0, comps=0, market=None)
        else:
            result = _stub_result
    monkeypatch.setattr(
        "cardplatform.sealed.engine.SealedDealEngine.assess",
        lambda self, q, limit=20: result(q) if callable(result) else result,
    )
    return TestClient(app)


def test_sealed_deals_returns_ranked_deals(monkeypatch):
    client = _client(monkeypatch, _stub_result(listings=2, market=120.0))
    r = client.get("/sealed/deals", params={"q": "scarlet violet booster box", "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "scarlet violet booster box"
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is False
    assert body["comps_unavailable"] is False
    assert body["comps_empty"] is False  # comps present
    assert body["sealed_market"]["price"] == 120.0
    assert len(body["deals"]) == 2
    assert body["deals"][0]["flip_edge"] == 20.0
    assert body["thresholds"]["sealed_flip_min_abs"] == 20.0
    assert body["thresholds"]["sealed_flip_min_pct"] == 0.05


def test_sealed_deals_no_key_means_listings_and_comps_unavailable(monkeypatch):
    client = _client(monkeypatch, key=None)
    r = client.get("/sealed/deals", params={"q": "booster box"})
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is True
    assert body["comps_unavailable"] is True
    assert body["deals"] == []  # engine still runs but provider returns []


def test_sealed_deals_empty_query_returns_422(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/sealed/deals", params={"q": "  "})
    assert r.status_code == 422  # whitespace-only query rejected


def test_sealed_deals_limit_rejected_out_of_range(monkeypatch):
    # Query(20, ge=1, le=50) rejects out-of-range limits with 422 (the honest
    # constraint — no silent clamp to 50, per the explicit spec).
    client = _client(monkeypatch, _stub_result())
    assert client.get("/sealed/deals", params={"q": "box", "limit": 999}).status_code == 422
    assert client.get("/sealed/deals", params={"q": "box", "limit": 0}).status_code == 422
    # In-range limit is echoed.
    r = client.get("/sealed/deals", params={"q": "box", "limit": 25})
    assert r.status_code == 200
    assert r.json()["limit"] == 25


def test_sealed_deals_missing_query_returns_422(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/sealed/deals").status_code == 422


def test_sealed_deals_listings_empty_when_key_set_but_no_listings(monkeypatch):
    client = _client(monkeypatch, _stub_result(query="box", listings=0, comps=3, market=120.0))
    body = client.get("/sealed/deals", params={"q": "box"}).json()
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is True       # key set, but 0 listings
    assert body["comps_empty"] is False          # comps present
    assert body["deals"] == []


def test_sealed_deals_no_comps_means_sealed_market_null_and_flip_edges_null(monkeypatch):
    client = _client(monkeypatch, _stub_result(listings=1, comps=0, market=None))
    body = client.get("/sealed/deals", params={"q": "box"}).json()
    assert body["sealed_market"] is None
    assert body["comps_empty"] is True  # key set, 0 comps
    assert body["deals"][0]["flip_edge"] is None  # never $0
