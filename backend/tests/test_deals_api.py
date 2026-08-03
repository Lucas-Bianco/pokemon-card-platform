"""T3: deals HTTP endpoints — per-card ranked deals + cross-card feed.

Pins the contract: unknown card 404; no `listings_api_key` configured ->
`listings_unavailable: true` (honest — no provider configured, never fake
listings); provider configured but no listings -> `listings_empty: true`;
ranked deals populated with rip/flip edges when listings + market inputs
exist. Missing raw/graded inputs null the edge — never a fabricated $0.

Mirrors test_listings_api.py: a `seeded` fixture (CardSet+Card) + `client`
TestClient with get_session overridden to that session. Settings overrides
replace `cardplatform.api.settings` (the same binding `create_app()` closes
over), matching the listings endpoint's monkeypatch idiom.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet


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


def test_deals_endpoint_returns_ranked_deals(client, db, tmp_path, monkeypatch):
    """Listings + raw market + psa10 comp -> ranked deal with rip/flip edges."""
    from cardplatform.db.models import (
        GradedPriceSnapshot,
        ListingSnapshot,
        PriceSnapshot,
    )

    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))

    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=120.0,
            source_updated_at="2026-08-01",
        )
    )
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=10.0,
            variant="holofoil",
            market=200.0,
            source="pkmnprices",
            source_updated_at="2026-08-01",
        )
    )
    db.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="holofoil",
            source="ebay",
            listing_id="L1",
            title="Charizard",
            price=80.0,
            currency="USD",
            listing_type="fixed_price",
            url="u",
            condition="Raw",
            source_updated_at="",
        )
    )
    db.commit()

    r = client.get("/cards/base1-4/deals", params={"variant": "holofoil"})
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is False
    d = body["deals"][0]
    assert d["listing_id"] == "L1"
    assert d["rip_edge"] == 40.0
    assert d["flip_edge_to_10"] == 95.0  # 200 - 80 - 25 fee
    assert d["is_rip"] is True and d["is_flip"] is True
    assert d["raw_market"]["price"] == 120.0
    assert d["raw_market"]["source"] == "tcgplayer"
    assert "thresholds" in body


def test_deals_endpoint_unknown_card_404(client):
    r = client.get("/cards/nope-1/deals")
    assert r.status_code == 404


def test_deals_endpoint_listings_unavailable_when_no_key(client):
    """Default settings have no listings_api_key -> honest unavailable flag."""
    r = client.get("/cards/base1-4/deals", params={"variant": "holofoil"})
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is True
    assert body["deals"] == []


def test_deals_endpoint_listings_empty_when_key_set_no_rows(client, tmp_path, monkeypatch):
    """Key set but no listings -> queried the source, just empty."""
    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))

    r = client.get("/cards/base1-4/deals", params={"variant": "holofoil"})
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is True
    assert body["deals"] == []


def test_deals_feed_defaults_to_watched_cards(client, db, tmp_path, monkeypatch):
    """GET /deals with no card_ids assesses the user's active watched cards.

    The feed assesses the empty variant per card (the common case for raw
    listings), so the seeded listing uses variant="".
    """
    from cardplatform.db.models import ListingSnapshot, PriceSnapshot, Watch

    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))

    db.add(
        Watch(
            card_id="base1-4",
            alert_type="price_target",
            target_price=100.0,
            active=True,
        )
    )
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="",
            market=120.0,
            source_updated_at="2026-08-01",
        )
    )
    db.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="",
            source="ebay",
            listing_id="L1",
            title="c",
            price=100.0,
            currency="USD",
            listing_type="fixed_price",
            url="u",
            condition="Raw",
            source_updated_at="",
        )
    )
    db.commit()

    r = client.get("/deals")
    assert r.status_code == 200
    body = r.json()
    assert any(d["listing_id"] == "L1" for d in body["deals"])


def test_deals_feed_explicit_card_ids(client, db, tmp_path, monkeypatch):
    """GET /deals?card_ids=base1-4 assesses only the listed cards."""
    from cardplatform.db.models import ListingSnapshot, PriceSnapshot

    monkeypatch.setattr("cardplatform.api.settings", _keyed_settings(tmp_path))

    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="",
            market=120.0,
            source_updated_at="2026-08-01",
        )
    )
    db.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="",
            source="ebay",
            listing_id="L1",
            title="c",
            price=100.0,
            currency="USD",
            listing_type="fixed_price",
            url="u",
            condition="Raw",
            source_updated_at="",
        )
    )
    db.commit()

    r = client.get("/deals", params={"card_ids": "base1-4", "limit": 5})
    assert r.status_code == 200
    assert len(r.json()["deals"]) == 1