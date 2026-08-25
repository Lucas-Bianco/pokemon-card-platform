"""HTTP boundary tests for the want list / hunt list (roadmap row 24).

Pins the wire contract: GET /wants is read-only and honest (market_price null
never $0; deal_gap/within_target null when either side missing); POST /wants/items
is 201 / 404 (unknown card) / 409 (duplicate); PATCH sets+clears target_price
and note, omitted fields left intact, 404 for a missing slot (even with no
fields); DELETE is 204 then 404. Mirrors test_binder_api.py: direct inserts + a
dependency override for get_session. No network provider to stub — the want
route reads price snapshots straight from the DB via PriceService.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot


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


def _snap(session, card_id, source, variant, market, source_updated_at="2026/07/28"):
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            source_updated_at=source_updated_at,
        )
    )
    session.commit()


def _add(client, card_id, **body):
    return client.post("/wants/items", json={"card_id": card_id, **body})


def test_get_wants_empty(client):
    r = client.get("/wants")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_add_item_returns_joined_slot(client):
    r = _add(client, "base1-4", target_price=50.0, note="grail")
    assert r.status_code == 201
    body = r.json()
    assert body["card_id"] == "base1-4"
    assert body["variant"] == "normal"
    assert body["target_price"] == 50.0
    assert body["note"] == "grail"
    assert body["card_name"] == "Charizard"
    assert body["set_name"] == "Base"
    assert body["number"] == "4"
    assert body["rarity"] == "Rare Holo"
    # No snapshot yet -> honest nulls, never $0.
    assert body["market_price"] is None
    assert body["market_source"] is None
    assert body["deal_gap"] is None
    assert body["within_target"] is None


def test_add_unknown_card_404(client):
    r = _add(client, "nope-1")
    assert r.status_code == 404


def test_add_duplicate_409(client):
    _add(client, "base1-4")
    r = _add(client, "base1-4")
    assert r.status_code == 409


def test_get_after_add_round_trips(client, seeded):
    _snap(seeded, "base1-4", "tcgplayer", "normal", market=40.0)
    _add(client, "base1-4", target_price=50.0)
    r = client.get("/wants")
    body = r.json()["items"][0]
    assert body["market_price"] == 40.0
    assert body["market_source"] == "tcgplayer"
    assert body["market_source_updated_at"] == "2026/07/28"
    assert body["deal_gap"] == pytest.approx(10.0)
    assert body["within_target"] is True


def test_over_target_within_target_false(client, seeded):
    _snap(seeded, "base1-4", "tcgplayer", "normal", market=60.0)
    _add(client, "base1-4", target_price=50.0)
    body = client.get("/wants").json()["items"][0]
    assert body["deal_gap"] == pytest.approx(-10.0)
    assert body["within_target"] is False


def test_no_target_no_deal_gap(client, seeded):
    _snap(seeded, "base1-4", "tcgplayer", "normal", market=40.0)
    _add(client, "base1-4")
    body = client.get("/wants").json()["items"][0]
    assert body["target_price"] is None
    assert body["deal_gap"] is None
    assert body["within_target"] is None


def test_patch_sets_target_price(client):
    _add(client, "base1-4")
    r = client.patch("/wants/items/base1-4/normal", json={"target_price": 75.0})
    assert r.status_code == 200
    assert r.json()["target_price"] == 75.0


def test_patch_clears_target_price_with_null(client):
    _add(client, "base1-4", target_price=50.0)
    r = client.patch("/wants/items/base1-4/normal", json={"target_price": None})
    assert r.status_code == 200
    assert r.json()["target_price"] is None


def test_patch_sets_note(client):
    _add(client, "base1-4")
    r = client.patch("/wants/items/base1-4/normal", json={"note": "gift"})
    assert r.status_code == 200
    assert r.json()["note"] == "gift"


def test_patch_omitted_field_left_intact(client):
    _add(client, "base1-4", target_price=50.0, note="orig")
    # Only patch the note; target_price omitted must stay 50.0.
    r = client.patch("/wants/items/base1-4/normal", json={"note": "new"})
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "new"
    assert body["target_price"] == 50.0


def test_patch_both_fields_at_once(client):
    _add(client, "base1-4")
    r = client.patch(
        "/wants/items/base1-4/normal", json={"target_price": 30.0, "note": "both"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target_price"] == 30.0
    assert body["note"] == "both"


def test_patch_no_fields_still_404_for_missing_slot(client):
    # A no-op patch on a slot that isn't in the want list tells the truth: 404.
    r = client.patch("/wants/items/base1-4/normal", json={})
    assert r.status_code == 404


def test_patch_existing_slot_no_fields_ok(client):
    _add(client, "base1-4", target_price=50.0)
    r = client.patch("/wants/items/base1-4/normal", json={})
    assert r.status_code == 200
    assert r.json()["target_price"] == 50.0  # unchanged


def test_patch_missing_slot_404(client):
    r = client.patch("/wants/items/base1-4/normal", json={"target_price": 10.0})
    assert r.status_code == 404


def test_delete_204_then_404(client):
    _add(client, "base1-4")
    r = client.delete("/wants/items/base1-4/normal")
    assert r.status_code == 204
    r = client.delete("/wants/items/base1-4/normal")
    assert r.status_code == 404
    assert client.get("/wants").json()["items"] == []


def test_variant_slot_distinct(client, seeded):
    _snap(seeded, "base1-4", "tcgplayer", "reverseHolofoil", market=200.0)
    _add(client, "base1-4", variant="reverseHolofoil", target_price=180.0)
    body = client.get("/wants").json()["items"][0]
    assert body["variant"] == "reverseHolofoil"
    assert body["market_price"] == 200.0
    assert body["deal_gap"] == pytest.approx(-20.0)


def test_route_does_not_shadow_parametric_routes(client):
    # Literal /wants/items must not be captured by /wants/items/{card_id}/{variant}.
    r = client.post("/wants/items", json={"card_id": "base1-4"})
    assert r.status_code == 201
    # And GET /wants (the collection) is distinct from /wants/items/...
    assert client.get("/wants").status_code == 200