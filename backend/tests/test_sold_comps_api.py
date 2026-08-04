"""T2: GET /cards/{id}/sold-comps — recent eBay sold listings as sale evidence.

Mirrors test_deals_api.py: a `seeded` fixture (CardSet+Card) + `client`
TestClient with get_session overridden. Settings overrides replace
`cardplatform.api.settings`. EbayListingsProvider.fetch_sold_listings is
stubbed so no network call is made. Honest flags: no key ->
sold_comps_unavailable true; key set but no comps -> sold_comps_empty true.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.prices.listings_provider import SoldComp


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def _keyed_settings(tmp_path):
    return Settings(data_dir=tmp_path, listings_api_key="an-app-id")


def _comp(listing_id="a", price=118.0, currency="USD"):
    return SoldComp(
        card_id="base1-4", variant="", listing_id=listing_id, price=price,
        currency=currency, url="https://ebay.example/x", condition="Used",
        sold_at=datetime(2026, 7, 30, 18, 30, tzinfo=timezone.utc),
        title="Charizard #4", source="ebay",
    )


def _stub_fetch(monkeypatch, comps):
    from cardplatform.prices import ebay_listings as mod
    monkeypatch.setattr(
        mod.EbayListingsProvider, "fetch_sold_listings",
        lambda self, card_id, variant, limit=3: comps,
    )


def test_sold_comps_returns_comps(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))
    _stub_fetch(monkeypatch, [_comp("a", 118.0), _comp("b", 121.0), _comp("c", 119.0)])

    r = client.get("/cards/base1-4/sold-comps", params={"variant": "", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["card_id"] == "base1-4"
    assert body["variant"] == ""
    assert body["sold_comps_unavailable"] is False
    assert body["sold_comps_empty"] is False
    assert [c["listing_id"] for c in body["sold_comps"]] == ["a", "b", "c"]
    assert body["sold_comps"][0]["price"] == 118.0
    assert body["sold_comps"][0]["source"] == "ebay"
    assert body["sold_comps"][0]["sold_at"].startswith("2026-07-30")


def test_sold_comps_unavailable_when_no_key(client):
    """Default settings have no listings_api_key -> honest unavailable flag."""
    r = client.get("/cards/base1-4/sold-comps")
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps_unavailable"] is True
    assert body["sold_comps_empty"] is False
    assert body["sold_comps"] == []


def test_sold_comps_empty_when_key_set_no_results(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))
    _stub_fetch(monkeypatch, [])

    r = client.get("/cards/base1-4/sold-comps")
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps_unavailable"] is False
    assert body["sold_comps_empty"] is True
    assert body["sold_comps"] == []


def test_sold_comps_limit_clamped_to_max(client, tmp_path, monkeypatch):
    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))
    captured = {}
    from cardplatform.prices import ebay_listings as mod

    def fake(self, card_id, variant, limit=3):
        captured["limit"] = limit
        return [_comp(str(i)) for i in range(limit)]

    monkeypatch.setattr(mod.EbayListingsProvider, "fetch_sold_listings", fake)

    r = client.get("/cards/base1-4/sold-comps", params={"limit": 99})
    assert r.status_code == 200
    assert captured["limit"] == 10  # clamped to max 10
    assert len(r.json()["sold_comps"]) == 10


def test_sold_comps_unknown_card_404(client):
    r = client.get("/cards/nope-1/sold-comps")
    assert r.status_code == 404