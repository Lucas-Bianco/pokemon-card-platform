from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            image_small="https://images.example/base1-4/small.png",
            image_large="https://images.example/base1-4/large.png",
        )
    )
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app.dependency_overrides[get_session] = lambda: seeded
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def snapshot(session, card_id="base1-4", source="tcgplayer", variant="holofoil", **kwargs):
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            **kwargs,
        )
    )
    session.commit()


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_card_resolves_set_name_from_the_relationship(client):
    response = client.get("/cards/base1-4")

    assert response.status_code == 200
    assert response.json() == {
        "id": "base1-4",
        "name": "Charizard",
        "number": "4",
        "rarity": "Rare Holo",
        "set_id": "base1",
        "set_name": "Base",
        "image_small": "https://images.example/base1-4/small.png",
        "image_large": "https://images.example/base1-4/large.png",
    }


def test_get_missing_card_returns_404(client):
    response = client.get("/cards/no-such-card")

    assert response.status_code == 404
    assert "no-such-card" in response.json()["detail"]


def test_search_matches_a_lowercase_substring_of_a_capitalised_name(client):
    """Users type 'chari', the catalog stores 'Charizard'. A case-sensitive LIKE
    would return nothing and make the search look broken."""
    response = client.get("/cards", params={"name": "chari"})

    assert response.status_code == 200
    assert [card["id"] for card in response.json()] == ["base1-4"]


def test_prices_include_the_source_timestamp(client, seeded):
    snapshot(
        seeded,
        low=100.0,
        mid=150.0,
        high=400.0,
        market=172.5,
        source_updated_at="2026/07/28",
        fetched_at=NOW,
    )

    response = client.get("/cards/base1-4/prices")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["source"] == "tcgplayer"
    assert body[0]["variant"] == "holofoil"
    assert body[0]["low"] == 100.0
    assert body[0]["mid"] == 150.0
    assert body[0]["high"] == 400.0
    assert body[0]["market"] == 172.5
    assert body[0]["source_updated_at"] == "2026/07/28"


def test_prices_return_only_the_newest_snapshot_per_source_and_variant(client, seeded):
    """Snapshots are append-only history, so a card accrues many rows for the same
    (source, variant). The endpoint must collapse them to the current price; returning
    the whole history would show the UI a stale number alongside the live one."""
    snapshot(seeded, market=5.00, source_updated_at="2026/07/01", fetched_at=NOW - timedelta(days=28))
    snapshot(seeded, market=11.02, source_updated_at="2026/07/29", fetched_at=NOW)

    body = client.get("/cards/base1-4/prices").json()

    assert len(body) == 1
    assert body[0]["market"] == 11.02
    assert body[0]["source_updated_at"] == "2026/07/29"


def test_every_source_and_variant_pair_is_represented_with_its_own_timestamp(client, seeded):
    """tcgplayer refreshes daily and cardmarket lagged ~4 weeks in measurement. Both
    are returned side by side with their own stamps rather than blended into one
    number, so the UI can show how old each figure actually is."""
    snapshot(
        seeded,
        source="tcgplayer",
        variant="holofoil",
        market=11.02,
        source_updated_at="2026/07/29",
        fetched_at=NOW,
    )
    snapshot(
        seeded,
        source="cardmarket",
        variant="aggregate",
        market=2.67,
        source_updated_at="2026/07/01",
        fetched_at=NOW,
    )

    body = client.get("/cards/base1-4/prices").json()

    by_source = {entry["source"]: entry for entry in body}
    assert set(by_source) == {"tcgplayer", "cardmarket"}
    assert by_source["tcgplayer"]["variant"] == "holofoil"
    assert by_source["tcgplayer"]["source_updated_at"] == "2026/07/29"
    assert by_source["cardmarket"]["variant"] == "aggregate"
    assert by_source["cardmarket"]["source_updated_at"] == "2026/07/01"


def test_prices_for_an_unpriced_card_is_an_empty_list_not_a_404(client):
    """Most of the 20k-card catalog has never been priced. 'No prices yet' is a normal
    state for a card that exists, not a missing resource."""
    response = client.get("/cards/base1-58/prices")

    assert response.status_code == 200
    assert response.json() == []


def test_post_collection_creates_an_item_that_shows_up_in_the_listing(client):
    created = client.post(
        "/collection",
        json={"card_id": "base1-4", "variant": "holofoil", "quantity": 3, "acquired_price": 60.0},
    )

    assert created.status_code == 201
    assert created.json()["card_id"] == "base1-4"
    assert created.json()["quantity"] == 3

    listed = client.get("/collection")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["card_name"] == "Charizard"
    assert listed.json()[0]["variant"] == "holofoil"
    assert listed.json()[0]["quantity"] == 3


def test_post_collection_with_an_unknown_card_returns_404(client):
    """CollectionStore raises ValueError for an unknown card; unhandled that surfaces
    as a 500 and reads as a server bug rather than a bad request."""
    response = client.post("/collection", json={"card_id": "no-such-card"})

    assert response.status_code == 404
    assert "no-such-card" in response.json()["detail"]


def test_valuation_reflects_market_price_times_quantity(client, seeded):
    snapshot(seeded, market=100.0, source_updated_at="2026/07/28", fetched_at=NOW)
    client.post("/collection", json={"card_id": "base1-4", "variant": "holofoil", "quantity": 2,
                                     "acquired_price": 60.0})

    body = client.get("/collection/valuation").json()

    assert body == {
        "market_value": 200.0,
        "cost_basis": 120.0,
        "unrealized": 80.0,
        "unpriced_items": 0,
    }


def test_limit_is_honored_and_capped(client, seeded):
    seeded.add(Card(id="base1-3", set_id="base1", name="Charizard EX", number="3"))
    seeded.add(Card(id="base1-46", set_id="base1", name="Charmander", number="46"))
    seeded.commit()

    all_matches = client.get("/cards", params={"name": "char"}).json()
    assert [card["name"] for card in all_matches] == ["Charizard", "Charizard EX", "Charmander"]

    limited = client.get("/cards", params={"name": "char", "limit": 2}).json()
    assert [card["name"] for card in limited] == ["Charizard", "Charizard EX"]

    assert client.get("/cards", params={"name": "char", "limit": 101}).status_code == 422
