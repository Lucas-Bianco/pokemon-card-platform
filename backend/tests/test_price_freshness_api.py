"""Row 26 API: GET /collection/price-freshness — band the collection's priced
holdings by the age of their latest price snapshot's fetched_at. The route has no
`now` query param (staleness is measured against the real wall clock at request
time), so tests use snapshots fetched at controlled offsets from now to land in
specific bands. Four bands always present in order; unpriced counted separately,
never $0; caveat always present.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


def _days_ago(n):
    return datetime.now(timezone.utc) - timedelta(days=n)


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


def _bands(body):
    return {b["label"]: b for b in body["bands"]}


def test_freshness_empty_collection_returns_four_zero_bands(client):
    r = client.get("/collection/price-freshness")
    assert r.status_code == 200
    body = r.json()
    assert [b["label"] for b in body["bands"]] == ["fresh", "aging", "stale", "outdated"]
    for b in body["bands"]:
        assert b["holdings"] == 0
        assert b["market_value"] == 0.0
    assert body["priced_holdings"] == 0
    assert body["unpriced_holdings"] == 0
    assert body["total_holdings"] == 0
    assert body["oldest_fetched_at"] is None
    assert body["newest_fetched_at"] is None
    assert body["caveat"]


def test_freshness_holdings_no_snapshots_all_unpriced_never_zero(client):
    _hold("base1-4")
    _hold("base1-58")
    r = client.get("/collection/price-freshness")
    body = r.json()
    assert body["priced_holdings"] == 0
    assert body["unpriced_holdings"] == 2
    assert body["total_holdings"] == 2
    for b in body["bands"]:
        assert b["holdings"] == 0
        assert b["market_value"] == 0.0


def test_freshness_fresh_holding_lands_in_fresh_band(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _days_ago(3))
    r = client.get("/collection/price-freshness")
    body = r.json()
    b = _bands(body)
    assert b["fresh"]["holdings"] == 1
    assert b["fresh"]["market_value"] == 10.0
    assert b["fresh"]["share"] == 1.0
    assert body["priced_holdings"] == 1
    assert body["unpriced_holdings"] == 0


def test_freshness_all_four_bands_populated(client):
    _hold("base1-4", variant="normal", quantity=1)
    _hold("base1-4", variant="holofoil", quantity=1)
    _hold("base1-58", variant="normal", quantity=1)
    _hold("base1-58", variant="holofoil", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _days_ago(3))      # fresh
    _snap("base1-4", "tcgplayer", "holofoil", 20.0, _days_ago(10))   # aging
    _snap("base1-58", "tcgplayer", "normal", 30.0, _days_ago(45))    # stale
    _snap("base1-58", "tcgplayer", "holofoil", 40.0, _days_ago(100)) # outdated
    r = client.get("/collection/price-freshness")
    body = r.json()
    b = _bands(body)
    assert b["fresh"]["holdings"] == 1
    assert b["aging"]["holdings"] == 1
    assert b["stale"]["holdings"] == 1
    assert b["outdated"]["holdings"] == 1
    assert body["priced_holdings"] == 4
    assert body["priced_value_total"] == 100.0
    # share floats rounded on the wire; sum across bands ~1.0
    assert round(sum(x["share"] for x in body["bands"]), 6) == 1.0


def test_freshness_snapshot_with_null_market_is_unpriced(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "tcgplayer", "normal", None, _days_ago(3))
    r = client.get("/collection/price-freshness")
    body = r.json()
    assert body["priced_holdings"] == 0
    assert body["unpriced_holdings"] == 1
    for b in body["bands"]:
        assert b["holdings"] == 0


def test_freshness_quantity_multiplies_band_value(client):
    _hold("base1-4", quantity=3)
    _snap("base1-4", "tcgplayer", "normal", 10.0, _days_ago(2))
    r = client.get("/collection/price-freshness")
    body = r.json()
    b = _bands(body)
    assert b["fresh"]["market_value"] == 30.0
    assert b["fresh"]["quantity"] == 3


def test_freshness_oldest_and_newest_fetched_at_present(client):
    _hold("base1-4", variant="normal", quantity=1)
    _hold("base1-4", variant="holofoil", quantity=1)
    old = _days_ago(100)
    new = _days_ago(2)
    _snap("base1-4", "tcgplayer", "normal", 10.0, old)
    _snap("base1-4", "tcgplayer", "holofoil", 20.0, new)
    r = client.get("/collection/price-freshness")
    body = r.json()
    # wire datetimes are ISO strings; compare by prefix date, tolerant of sub-second
    assert body["oldest_fetched_at"].startswith(old.strftime("%Y-%m-%d"))
    assert body["newest_fetched_at"].startswith(new.strftime("%Y-%m-%d"))


def test_freshness_cardmarket_fallback_prices_a_holding(client):
    _hold("base1-4", quantity=1)
    _snap("base1-4", "cardmarket", "aggregate", 18.0, _days_ago(40))
    r = client.get("/collection/price-freshness")
    body = r.json()
    b = _bands(body)
    assert body["priced_holdings"] == 1
    assert b["stale"]["holdings"] == 1
    assert b["stale"]["market_value"] == 18.0


def test_freshness_route_does_not_shadow_portfolio_history(client):
    # /collection/price-freshness is registered before the parametric PATCH
    # /{item_id}; GET /collection/portfolio/history must still resolve.
    r = client.get("/collection/portfolio/history")
    assert r.status_code == 200
    assert "points" in r.json()