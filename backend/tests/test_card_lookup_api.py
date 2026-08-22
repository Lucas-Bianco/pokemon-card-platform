"""Phase D: GET /cards/lookup?q=&limit= — the Prices tab's name -> price lookup.

Mirrors test_price_api.py's seeding (CardSet + Card + PriceSnapshot) and
test_sealed_catalog_api.py's get_session override. The route builds its own
PriceService(session), so no provider override is needed — latest_price reads
the seeded PriceSnapshot. Honest: a card with no snapshot has market=None (never
0); min_length=2 gives a clean 422 for blank/1-char queries.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", rarity="Rare"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58", rarity="Common"))
    # A Charizard-with-suffix to prove substring + ordering by name.
    db.add(Card(id="base1-4b", set_id="base1", name="Charizard ex", number="4b", rarity="Rare"))
    db.commit()
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="normal",
            market=800.43,
            source_updated_at="2026/07/29",
        )
    )
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app.dependency_overrides[get_session] = lambda: seeded
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_lookup_matches_by_substring(client):
    r = client.get("/cards/lookup", params={"q": "char"})
    assert r.status_code == 200
    body = r.json()
    names = [item["name"] for item in body]
    assert "Charizard" in names
    assert "Charizard ex" in names
    assert "Pikachu" not in names


def test_lookup_attaches_latest_price(client):
    r = client.get("/cards/lookup", params={"q": "Charizard"})
    body = r.json()
    zard = next(item for item in body if item["name"] == "Charizard")
    assert zard["market"] == 800.43
    assert zard["source"] == "tcgplayer"
    assert zard["source_updated_at"] == "2026/07/29"
    assert zard["set_name"] == "Base"
    assert zard["number"] == "4"
    assert zard["rarity"] == "Rare"
    assert zard["card_id"] == "base1-4"


def test_lookup_unpriced_card_is_null_not_zero(client):
    """Charizard ex has no snapshot -> market is None (honest), never a fabricated 0."""
    r = client.get("/cards/lookup", params={"q": "Charizard ex"})
    body = r.json()
    assert len(body) == 1
    item = body[0]
    assert item["name"] == "Charizard ex"
    assert item["market"] is None
    assert item["source"] is None
    assert item["source_updated_at"] is None


def test_lookup_orders_by_name(client):
    r = client.get("/cards/lookup", params={"q": "char"})
    body = r.json()
    names = [item["name"] for item in body]
    # "Charizard" sorts before "Charizard ex".
    assert names == sorted(names)


def test_lookup_no_matches_is_empty_list(client):
    r = client.get("/cards/lookup", params={"q": "zzzzz"})
    assert r.status_code == 200
    assert r.json() == []


def test_lookup_blank_query_422(client):
    assert client.get("/cards/lookup", params={"q": ""}).status_code == 422


def test_lookup_one_char_query_422(client):
    # min_length=2 rejects a 1-char query before the service runs.
    assert client.get("/cards/lookup", params={"q": "x"}).status_code == 422


def test_lookup_limit_out_of_range_422(client):
    assert client.get("/cards/lookup", params={"q": "char", "limit": 0}).status_code == 422
    assert client.get("/cards/lookup", params={"q": "char", "limit": 51}).status_code == 422


def test_lookup_is_case_insensitive(client):
    r = client.get("/cards/lookup", params={"q": "PIKA"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "Pikachu"