"""Row 25 API: GET /collection/portfolio/history — reconstructed portfolio market
value over time, from append-only snapshots. Honest empty state (no points when
there is no price history, never a $0 point); current-holdings + cadence caveat
always present."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


@pytest.fixture
def client(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(
        Card(
            id="base1-4", set_id="base1", name="Charizard", number="4",
            rarity="Rare Holo", supertype="Pokemon",
        )
    )
    db.add(
        Card(
            id="base1-58", set_id="base1", name="Pikachu", number="58",
            rarity="Common", supertype="Pokemon",
        )
    )
    db.commit()
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _db():
    return app.dependency_overrides[get_session]()


def _hold(card_id, variant="normal", quantity=1):
    db = _db()
    db.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.commit()


def _snap(card_id, source, variant, market, fetched_at, source_updated_at=None):
    db = _db()
    if source_updated_at is None:
        source_updated_at = fetched_at.strftime("%Y/%m/%d")
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant, market=market,
            fetched_at=fetched_at, source_updated_at=source_updated_at,
        )
    )
    db.commit()


def _t(month, day=1):
    return datetime(2026, month, day, 12, 0, 0, tzinfo=timezone.utc)


def test_history_empty_collection_returns_200_no_points(client):
    r = client.get("/collection/portfolio/history")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == []
    assert body["total_items"] == 0
    assert body["priced_items"] == 0
    assert body["unpriced_items"] == 0
    assert body["caveat"]


def test_history_holdings_no_snapshots_is_honest_empty_not_zero(client):
    _hold("base1-4")
    _hold("base1-58")
    r = client.get("/collection/portfolio/history")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == []  # no history yet, NOT a point at $0
    assert body["total_items"] == 2
    assert body["priced_items"] == 0
    assert body["unpriced_items"] == 2


def test_history_single_holding_single_point(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _t(1))
    r = client.get("/collection/portfolio/history")
    body = r.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["market_value"] == 10.0
    assert body["points"][0]["priced_items"] == 1
    assert body["points"][0]["unpriced_items"] == 0


def test_history_step_timeline_two_points(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _t(1))
    _snap("base1-4", "tcgplayer", "normal", 25.0, _t(2))
    r = client.get("/collection/portfolio/history")
    body = r.json()
    assert [p["market_value"] for p in body["points"]] == [10.0, 25.0]


def test_history_tcg_preferred_over_cardmarket(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _t(1))
    _snap("base1-4", "cardmarket", "aggregate", 20.0, _t(2))
    r = client.get("/collection/portfolio/history")
    body = r.json()
    assert [p["market_value"] for p in body["points"]] == [10.0, 10.0]


def test_history_multiple_holdings_summed(client):
    _hold("base1-4", quantity=2)
    _hold("base1-58", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _t(1))
    _snap("base1-58", "tcgplayer", "normal", 15.0, _t(2))
    r = client.get("/collection/portfolio/history")
    body = r.json()
    assert len(body["points"]) == 2
    assert body["points"][0]["market_value"] == 20.0  # only Charizard at t1
    assert body["points"][1]["market_value"] == 35.0  # both at t2


def test_history_since_query_preserves_pre_since_prices(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _t(1))
    _snap("base1-4", "tcgplayer", "normal", 25.0, _t(2))
    _snap("base1-4", "tcgplayer", "normal", 40.0, _t(3))
    r = client.get("/collection/portfolio/history", params={"since": _t(2).isoformat()})
    body = r.json()
    assert len(body["points"]) == 2
    assert [p["market_value"] for p in body["points"]] == [25.0, 40.0]


def test_history_route_does_not_shadow_collection_portfolio(client):
    # The literal /collection/portfolio/history is registered before the parametric
    # PATCH /collection/{item_id}, so GET /collection/portfolio (the existing
    # portfolio read) must still resolve.
    r = client.get("/collection/portfolio")
    assert r.status_code == 200
    assert "summary" in r.json()