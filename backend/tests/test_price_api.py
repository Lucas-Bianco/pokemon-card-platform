import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_price_provider, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.prices.provider import PriceQuote


class StubProvider:
    name = "stub"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch(self, card_id):
        self.calls.append(card_id)
        return [q for q in self.quotes if q.card_id == card_id]


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=800.43,
            source_updated_at="2026/07/29",
        )
    )
    db.commit()
    return db


def _client(db, provider=None):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    stub = provider or StubProvider([])
    app.dependency_overrides[get_price_provider] = lambda: stub
    return TestClient(app), stub


def test_resolved_price_returns_the_cached_snapshot(seeded):
    client, _ = _client(seeded)

    response = client.get("/cards/base1-4/price", params={"variant": "holofoil"})

    assert response.status_code == 200
    body = response.json()
    assert body["market"] == 800.43
    assert body["source"] == "tcgplayer"
    assert body["source_updated_at"] == "2026/07/29"


def test_resolved_price_is_204_when_unpriced(seeded):
    """A card with no price is a normal state, not an error."""
    client, _ = _client(seeded)

    response = client.get("/cards/base1-58/price")

    assert response.status_code == 204
    assert response.content == b""


def test_resolved_price_404s_for_an_unknown_card(seeded):
    client, _ = _client(seeded)

    assert client.get("/cards/nope-1/price").status_code == 404


def test_resolved_price_does_not_call_the_provider(seeded):
    """This endpoint reads cache only; fetching is the refresh endpoint's job."""
    client, stub = _client(seeded)

    client.get("/cards/base1-58/price")

    assert stub.calls == []


def test_refresh_fetches_and_returns_the_new_price(seeded):
    provider = StubProvider(
        [PriceQuote("base1-58", "tcgplayer", "normal", market=12.5, source_updated_at="2026/07/29")]
    )
    client, stub = _client(seeded, provider)

    response = client.post("/cards/base1-58/prices/refresh", params={"variant": "normal"})

    assert response.status_code == 200
    assert response.json()["market"] == 12.5
    assert stub.calls == ["base1-58"]


def test_refresh_returns_204_when_the_source_has_nothing(seeded):
    client, _ = _client(seeded, StubProvider([]))

    response = client.post("/cards/base1-58/prices/refresh")

    assert response.status_code == 204
    assert response.content == b""


def test_refresh_404s_for_an_unknown_card(seeded):
    client, _ = _client(seeded)

    assert client.post("/cards/nope-1/prices/refresh").status_code == 404
