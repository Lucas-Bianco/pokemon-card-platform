"""Row 23 API: GET /collection/diversification — concentration + diversification
of the collection's priced value, with honest unpriced handling (never $0)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def client(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Gym"))
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
    db.add(
        Card(
            id="base2-1", set_id="base2", name="Energy", number="1",
            rarity="Common", supertype="Energy",
        )
    )
    db.commit()
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _snap(card_id, source, variant, market, stamp="2026/07/28"):
    db = app.dependency_overrides[get_session]()
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant,
            market=market, source_updated_at=stamp,
        )
    )
    db.commit()


def _add(client, card_id, variant="normal", quantity=1):
    r = client.post(
        "/collection", json={"card_id": card_id, "variant": variant, "quantity": quantity}
    )
    assert r.status_code == 201, r.text


def test_diversification_empty_collection(client):
    r = client.get("/collection/diversification")
    assert r.status_code == 200
    body = r.json()
    assert body["priced_total"] == 0.0
    assert body["priced_items"] == 0
    assert body["unpriced_items"] == 0
    assert body["total_items"] == 0
    assert body["top_holdings"] == []
    assert body["concentration"]["top_share"] is None
    assert body["concentration"]["cards_for_50"] is None
    assert body["concentration"]["priced_holdings"] == 0
    assert body["by_rarity"] == []
    assert body["caveat"]


def test_diversification_priced_holding_round_trips_with_share(client):
    _snap("base1-4", "tcgplayer", "normal", market=100.0)
    _add(client, "base1-4", quantity=2)

    body = client.get("/collection/diversification").json()
    assert body["priced_total"] == 200.0
    assert body["priced_items"] == 1
    assert body["unpriced_items"] == 0
    top = body["top_holdings"][0]
    assert top["card_id"] == "base1-4"
    assert top["card_name"] == "Charizard"
    assert top["set_name"] == "Base"
    assert top["variant"] == "normal"
    assert top["quantity"] == 2
    assert top["market_value"] == 200.0
    assert top["share"] == 1.0
    assert top["cumulative_share"] == 1.0
    c = body["concentration"]
    assert c["top_share"] == 1.0
    assert c["cards_for_50"] == 1
    assert c["cards_for_80"] == 1
    assert c["cards_for_90"] == 1
    assert c["priced_holdings"] == 1


def test_diversification_unpriced_excluded_from_totals_counted_never_zero(client):
    _snap("base1-4", "tcgplayer", "normal", market=100.0)
    _add(client, "base1-4", quantity=1)        # priced
    _add(client, "base1-58", quantity=3)       # unpriced, no snapshot
    _add(client, "base2-1", quantity=1)       # unpriced, no snapshot

    body = client.get("/collection/diversification").json()
    assert body["priced_total"] == 100.0  # never fabricated
    assert body["priced_items"] == 1
    assert body["unpriced_items"] == 2
    assert body["total_items"] == 3
    # The priced holding is 100% of priced value, not diluted by unpriced.
    assert body["top_holdings"][0]["share"] == 1.0
    # Unpriced holdings still appear in buckets at market_value 0.
    by_set = {b["label"]: b for b in body["by_set"]}
    assert by_set["Base"]["market_value"] == 100.0
    assert by_set["Base"]["holdings"] == 2
    assert by_set["Jungle"]["market_value"] == 0.0
    assert by_set["Jungle"]["holdings"] == 1


def test_diversification_concentration_ratios_70_20_10(client):
    _snap("base1-4", "tcgplayer", "normal", market=70.0)
    _snap("base1-58", "tcgplayer", "normal", market=20.0)
    _snap("base2-1", "tcgplayer", "normal", market=10.0)
    _add(client, "base1-4", quantity=1)
    _add(client, "base1-58", quantity=1)
    _add(client, "base2-1", quantity=1)

    body = client.get("/collection/diversification").json()
    c = body["concentration"]
    assert c["top_share"] == pytest.approx(0.7)
    assert c["cards_for_50"] == 1   # 70% alone
    assert c["cards_for_80"] == 2  # 70+20 = 90% >= 80%
    assert c["cards_for_90"] == 2  # 90% >= 90% (epsilon-tolerant)
    assert c["priced_holdings"] == 3


def test_diversification_by_rarity_and_supertype_shares(client):
    _snap("base1-4", "tcgplayer", "normal", market=100.0)  # Rare Holo / Pokemon
    _snap("base2-1", "tcgplayer", "normal", market=50.0)    # Common / Energy
    _add(client, "base1-4", quantity=1)
    _add(client, "base2-1", quantity=1)

    body = client.get("/collection/diversification").json()
    assert body["priced_total"] == 150.0
    by_rarity = {b["label"]: b for b in body["by_rarity"]}
    assert by_rarity["Rare Holo"]["market_value"] == 100.0
    assert by_rarity["Rare Holo"]["share"] == pytest.approx(100.0 / 150.0)
    assert by_rarity["Common"]["market_value"] == 50.0
    by_super = {b["label"]: b for b in body["by_supertype"]}
    assert by_super["Pokemon"]["market_value"] == 100.0
    assert by_super["Energy"]["market_value"] == 50.0
    # Buckets sorted by market value desc.
    assert body["by_rarity"][0]["label"] == "Rare Holo"


def test_diversification_route_does_not_shadow_param_routes(client):
    # The literal /collection/diversification is registered before the
    # parameterised PATCH /collection/{item_id}; confirm both resolve and that
    # "diversification" is not captured as an item_id (it would 404 the PATCH).
    r = client.get("/collection/diversification")
    assert r.status_code == 200
    # PATCH /collection/{item_id} still works on a real id (here 9999 -> 404).
    r2 = client.patch("/collection/9999", json={"acquired_price": 10.0})
    assert r2.status_code == 404