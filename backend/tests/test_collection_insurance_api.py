"""Phase 18 API: GET /collection/insurance — replacement-value bands + schedule."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def client(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _snap(card_id, source, variant, market, low=None, high=None, stamp="2026/07/28"):
    db = app.dependency_overrides[get_session]()
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant,
            low=low, high=high, market=market, source_updated_at=stamp,
        )
    )
    db.commit()


def _add(client, card_id, variant="normal", quantity=1):
    r = client.post("/collection", json={"card_id": card_id, "variant": variant, "quantity": quantity})
    assert r.status_code == 201, r.text


def test_insurance_empty_collection(client):
    r = client.get("/collection/insurance")
    assert r.status_code == 200
    body = r.json()
    assert body["conservative"] == 0.0
    assert body["median"] == 0.0
    assert body["aggressive"] == 0.0
    assert body["priced_items"] == 0
    assert body["unpriced_items"] == 0
    assert body["schedule"] == []
    assert body["caveat"]


def test_insurance_three_bands_round_trip(client):
    _snap("base1-4", "tcgplayer", "normal", market=100.0, low=90.0, high=120.0)
    _add(client, "base1-4", quantity=2)

    body = client.get("/collection/insurance").json()
    assert body["conservative"] == 180.0  # 90 * 2
    assert body["median"] == 200.0  # 100 * 2
    assert body["aggressive"] == 240.0  # 120 * 2
    assert body["priced_items"] == 1
    assert body["unpriced_items"] == 0
    line = body["schedule"][0]
    assert line["card_id"] == "base1-4"
    assert line["card_name"] == "Charizard"
    assert line["set_name"] == "Base"
    assert line["low"] == 90.0
    assert line["market"] == 100.0
    assert line["high"] == 120.0
    assert line["source"] == "tcgplayer"
    assert line["source_updated_at"] == "2026/07/28"
    assert line["priced"] is True


def test_insurance_unpriced_excluded_and_empty_stamp_coerced(client):
    _snap("base1-4", "tcgplayer", "normal", market=100.0, low=90.0, high=120.0, stamp="")
    _add(client, "base1-4", quantity=1)
    _add(client, "base1-58", quantity=3)  # unpriced

    body = client.get("/collection/insurance").json()
    assert body["conservative"] == 90.0
    assert body["median"] == 100.0
    assert body["aggressive"] == 120.0
    assert body["priced_items"] == 1
    assert body["unpriced_items"] == 1

    priced = next(s for s in body["schedule"] if s["card_id"] == "base1-4")
    assert priced["source_updated_at"] is None  # "" sentinel -> None on the wire
    unpriced = next(s for s in body["schedule"] if s["card_id"] == "base1-58")
    assert unpriced["market"] is None
    assert unpriced["source"] is None
    assert unpriced["priced"] is False
    assert unpriced["source_updated_at"] is None