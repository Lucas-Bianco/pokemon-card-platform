"""HTTP boundary tests for the sold-lots ledger (roadmap row 29).

Pins the wire contract: GET /sold-lots is read-only and honest (proceeds
always present, cost_basis/realized null never $0); GET /sold-lots/summary
aggregates with total_realized over the cost-known subset only; POST
/sold-lots is 201 / 404 (unknown card) / 400 (bad input); DELETE
/sold-lots/{lot_id} is 204 then 404; the literal /sold-lots/summary route is
not shadowed by the parametric DELETE /sold-lots/{lot_id}. Mirrors
test_want_api.py: direct inserts + a dependency override for get_session.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Jungle"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", rarity="Rare Holo"))
    db.add(Card(id="base2-1", set_id="base2", name="Pikachu", number="1", rarity="Common"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def _add(client, card_id, **body):
    return client.post("/sold-lots", json={"card_id": card_id, "sale_price": 10.0, **body})


def test_get_sold_lots_empty(client):
    r = client.get("/sold-lots")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_summary_empty(client):
    r = client.get("/sold-lots/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["lot_count"] == 0
    assert body["lots_with_cost"] == 0
    assert body["lots_without_cost"] == 0
    assert body["total_proceeds"] == 0.0
    assert body["total_cost_basis"] == 0.0
    assert body["total_realized"] == 0.0
    assert body["winners"] == 0
    assert body["losers"] == 0
    assert body["caveat"]


def test_add_lot_returns_joined_entry(client):
    r = _add(client, "base1-4", quantity=2, sale_price=50.0, sale_fee=5.0,
             acquired_price=20.0, source="eBay", notes="graded")
    assert r.status_code == 201
    body = r.json()
    assert body["card_id"] == "base1-4"
    assert body["variant"] == "normal"
    assert body["quantity"] == 2
    assert body["sale_price"] == 50.0
    assert body["sale_fee"] == 5.0
    assert body["acquired_price"] == 20.0
    assert body["source"] == "eBay"
    assert body["notes"] == "graded"
    assert body["card_name"] == "Charizard"
    assert body["set_name"] == "Base"
    assert body["number"] == "4"
    assert body["proceeds"] == pytest.approx(90.0)
    assert body["cost_basis"] == pytest.approx(40.0)
    assert body["realized"] == pytest.approx(50.0)


def test_add_lot_without_cost_has_null_realized(client):
    r = _add(client, "base1-4", sale_price=30.0)
    assert r.status_code == 201
    body = r.json()
    assert body["proceeds"] == pytest.approx(30.0)
    assert body["cost_basis"] is None
    assert body["realized"] is None  # never $0


def test_add_unknown_card_404(client):
    r = _add(client, "nope-1")
    assert r.status_code == 404


def test_add_zero_quantity_400(client):
    r = _add(client, "base1-4", quantity=0)
    assert r.status_code == 400


def test_add_negative_sale_price_400(client):
    r = client.post("/sold-lots", json={"card_id": "base1-4", "sale_price": -1.0})
    assert r.status_code == 400


def test_add_accepts_explicit_sold_at_aware(client):
    r = _add(client, "base1-4",
             sold_at="2026-01-15T12:00:00Z")
    assert r.status_code == 201
    assert r.json()["sold_at"].startswith("2026-01-15T12:00:00")


def test_get_after_add_round_trips(client):
    _add(client, "base1-4", sale_price=50.0, acquired_price=20.0)
    body = client.get("/sold-lots").json()["items"][0]
    assert body["proceeds"] == pytest.approx(50.0)
    assert body["cost_basis"] == pytest.approx(20.0)
    assert body["realized"] == pytest.approx(30.0)


def test_summary_realized_over_cost_known_subset_only(client):
    _add(client, "base1-4", sale_price=50.0, acquired_price=20.0)  # realized +30
    _add(client, "base2-1", sale_price=30.0)  # no cost -> excluded from realized
    body = client.get("/sold-lots/summary").json()
    assert body["lot_count"] == 2
    assert body["lots_with_cost"] == 1
    assert body["lots_without_cost"] == 1
    assert body["total_proceeds"] == pytest.approx(80.0)
    assert body["total_cost_basis"] == pytest.approx(20.0)
    assert body["total_realized"] == pytest.approx(30.0)
    assert body["winners"] == 1
    assert body["losers"] == 0


def test_delete_204_then_404(client):
    lot_id = _add(client, "base1-4").json()["id"]
    r = client.delete(f"/sold-lots/{lot_id}")
    assert r.status_code == 204
    r = client.delete(f"/sold-lots/{lot_id}")
    assert r.status_code == 404
    assert client.get("/sold-lots").json()["items"] == []


def test_delete_nonexistent_404(client):
    assert client.delete("/sold-lots/99999").status_code == 404


def test_variant_lot_distinct(client):
    r = _add(client, "base1-4", variant="reverseHolofoil", sale_price=200.0)
    assert r.status_code == 201
    assert r.json()["variant"] == "reverseHolofoil"


def test_summary_route_not_shadowed_by_parametric_delete(client):
    # GET /sold-lots/summary is a literal that must resolve to the summary
    # route, not be captured as a lot_id by DELETE /sold-lots/{lot_id} (a
    # different verb, but confirm the literal GET wins on GET).
    r = client.get("/sold-lots/summary")
    assert r.status_code == 200
    assert "total_realized" in r.json()


def test_sold_lots_routes_do_not_shadow_collection_routes(client):
    # The /sold-lots namespace is distinct from /collection/*; confirm a
    # collection route still resolves alongside the sold-lots routes.
    assert client.get("/collection/portfolio").status_code == 200
    assert client.get("/sold-lots").status_code == 200