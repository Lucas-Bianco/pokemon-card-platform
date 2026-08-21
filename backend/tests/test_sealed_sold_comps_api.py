"""T1: GET /sealed/sold-comps — individual recently-sold eBay listings for a sealed-product
query, as the "proof of sales" behind the median market price (roadmap row 16).

Mirrors test_sold_comps_api.py (card sold-comps) + test_sealed_deals_api.py (query-keyed):
override `cardplatform.api.settings` with a real Settings, stub
`EbayListingsProvider.fetch_sold_listings_by_query` so no network is hit. Honest flags:
no key -> sold_comps_unavailable; key set but 0 comps -> sold_comps_empty. On-demand only,
never persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app
from cardplatform.config import Settings
from cardplatform.sealed.provider import SealedSoldComp


def _client(monkeypatch):
    app = create_app()
    return TestClient(app)


def _settings(tmp_path, key="an-app-id"):
    return Settings(data_dir=tmp_path, listings_api_key=key)


def _comp(listing_id="a", price=118.0, currency="USD"):
    return SealedSoldComp(
        query="scarlet violet booster box",
        listing_id=listing_id,
        price=price,
        currency=currency,
        url="https://ebay.example/x",
        condition="New",
        sold_at=datetime(2026, 7, 30, 18, 30, tzinfo=timezone.utc),
        title="Scarlet & Violet Booster Box",
        source="ebay",
    )


def _stub_fetch(monkeypatch, comps):
    from cardplatform.prices import ebay_listings as mod
    monkeypatch.setattr(
        mod.EbayListingsProvider,
        "fetch_sold_listings_by_query",
        lambda self, query, limit=6: comps,
    )


def test_sealed_sold_comps_returns_comps(monkeypatch, tmp_path):
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path))
    _stub_fetch(monkeypatch, [_comp("a", 118.0), _comp("b", 121.0), _comp("c", 119.0)])
    client = _client(monkeypatch)

    r = client.get("/sealed/sold-comps", params={"q": "scarlet violet booster box", "limit": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "scarlet violet booster box"
    assert body["limit"] == 6
    assert body["sold_comps_unavailable"] is False
    assert body["sold_comps_empty"] is False
    assert [c["listing_id"] for c in body["sold_comps"]] == ["a", "b", "c"]
    assert body["sold_comps"][0]["price"] == 118.0
    assert body["sold_comps"][0]["source"] == "ebay"
    assert body["sold_comps"][0]["sold_at"].startswith("2026-07-30")
    assert body["sold_comps"][0]["url"] == "https://ebay.example/x"


def test_sealed_sold_comps_unavailable_when_no_key(monkeypatch, tmp_path):
    """Default settings have no listings_api_key -> honest unavailable flag (not an error)."""
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path, key=None))
    _stub_fetch(monkeypatch, [])
    client = _client(monkeypatch)

    r = client.get("/sealed/sold-comps", params={"q": "scarlet violet booster box"})
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps_unavailable"] is True
    assert body["sold_comps_empty"] is False  # empty only counts when key set
    assert body["sold_comps"] == []


def test_sealed_sold_comps_empty_when_key_set_but_no_comps(monkeypatch, tmp_path):
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path))
    _stub_fetch(monkeypatch, [])
    client = _client(monkeypatch)

    r = client.get("/sealed/sold-comps", params={"q": "obscure product"})
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps_unavailable"] is False
    assert body["sold_comps_empty"] is True
    assert body["sold_comps"] == []


def test_sealed_sold_comps_blank_query_422(monkeypatch, tmp_path):
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path))
    _stub_fetch(monkeypatch, [])
    client = _client(monkeypatch)

    # min_length=2 rejects a 1-char query before our strip check.
    r = client.get("/sealed/sold-comps", params={"q": "x"})
    assert r.status_code == 422
    # whitespace-only is stripped to empty -> 422 (mirror /sealed/deals).
    r = client.get("/sealed/sold-comps", params={"q": "   "})
    assert r.status_code == 422


def test_sealed_sold_comps_limit_out_of_range_422(monkeypatch, tmp_path):
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path))
    _stub_fetch(monkeypatch, [])
    client = _client(monkeypatch)

    assert client.get("/sealed/sold-comps", params={"q": "booster box", "limit": 0}).status_code == 422
    assert client.get("/sealed/sold-comps", params={"q": "booster box", "limit": 11}).status_code == 422


def test_sealed_sold_comps_unknown_query_is_empty_not_error(monkeypatch, tmp_path):
    """A query eBay has no sold comps for is an honest empty, never a 5xx."""
    monkeypatch.setattr("cardplatform.api.settings", _settings(tmp_path))
    _stub_fetch(monkeypatch, [])
    client = _client(monkeypatch)

    r = client.get("/sealed/sold-comps", params={"q": "totally made up product xyz"})
    assert r.status_code == 200
    assert r.json()["sold_comps"] == []