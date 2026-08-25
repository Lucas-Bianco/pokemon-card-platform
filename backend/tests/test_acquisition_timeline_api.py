"""Row 27 API: GET /collection/acquisition-timeline — collection growth over
time. Cumulative card count (always populated, acquired_at defaults to now on
add) + cumulative cost basis (only holdings with a recorded purchase price,
never a fabricated $0). Undated holdings excluded, counted separately. Empty =
no points, never a point at 0.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem


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


def _hold(card_id, variant="normal", quantity=1, acquired_price=None, acquired_at=None):
    db = _db()
    db.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_price=acquired_price, acquired_at=acquired_at,
        )
    )
    db.commit()


def _t(month, day=1):
    return datetime(2026, month, day, 12, 0, 0, tzinfo=timezone.utc)


def test_timeline_empty_collection_returns_200_no_points(client):
    r = client.get("/collection/acquisition-timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == []
    assert body["total_holdings"] == 0
    assert body["total_cards"] == 0
    assert body["total_cost_basis"] == 0.0
    assert body["holdings_with_cost"] == 0
    assert body["holdings_without_cost"] == 0
    assert body["undated_holdings"] == 0
    assert body["caveat"]


def test_timeline_single_holding_one_point(client):
    _hold("base1-4", quantity=2, acquired_price=10.0, acquired_at=_t(1))
    r = client.get("/collection/acquisition-timeline")
    body = r.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["cumulative_cards"] == 2
    assert body["points"][0]["cumulative_cost_basis"] == 20.0


def test_timeline_cumulative_oldest_first(client):
    _hold("base1-4", quantity=1, acquired_price=10.0, acquired_at=_t(1))
    _hold("base1-58", quantity=3, acquired_price=5.0, acquired_at=_t(2))
    r = client.get("/collection/acquisition-timeline")
    body = r.json()
    assert [p["cumulative_cards"] for p in body["points"]] == [1, 4]
    assert [p["cumulative_cost_basis"] for p in body["points"]] == [10.0, 25.0]


def test_timeline_unpriced_acquisition_never_zero_cost(client):
    _hold("base1-4", quantity=2, acquired_price=10.0, acquired_at=_t(1))
    _hold("base1-58", quantity=3, acquired_price=None, acquired_at=_t(2))
    r = client.get("/collection/acquisition-timeline")
    body = r.json()
    assert [p["cumulative_cards"] for p in body["points"]] == [2, 5]
    assert [p["cumulative_cost_basis"] for p in body["points"]] == [20.0, 20.0]  # flat, not +0
    assert body["holdings_with_cost"] == 1
    assert body["holdings_without_cost"] == 1


def test_timeline_undated_holdings_excluded_counted(client):
    _hold("base1-4", quantity=1, acquired_price=10.0, acquired_at=_t(2))
    _hold("base1-58", quantity=2, acquired_at=None)
    r = client.get("/collection/acquisition-timeline")
    body = r.json()
    assert len(body["points"]) == 1
    assert body["undated_holdings"] == 1
    assert body["total_holdings"] == 2
    assert body["total_cards"] == 3


def test_timeline_totals_match(client):
    _hold("base1-4", quantity=2, acquired_price=10.0, acquired_at=_t(1))   # 20
    _hold("base1-58", quantity=3, acquired_price=4.0, acquired_at=_t(2))    # 12
    r = client.get("/collection/acquisition-timeline")
    body = r.json()
    assert body["total_cards"] == 5
    assert body["total_cost_basis"] == 32.0
    last = body["points"][-1]
    assert last["cumulative_cards"] == body["total_cards"]
    assert last["cumulative_cost_basis"] == body["total_cost_basis"]


def test_timeline_route_does_not_shadow_portfolio_endpoints(client):
    # /collection/acquisition-timeline is registered before the parametric PATCH
    # /{item_id}; the other literal collection reads must still resolve.
    assert client.get("/collection/portfolio").status_code == 200
    assert client.get("/collection/portfolio/history").status_code == 200
    assert client.get("/collection/price-freshness").status_code == 200