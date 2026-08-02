"""T5: watchlist HTTP endpoints — create/list/patch/delete over the `Watch` model.

Pins the honest-data contract at the boundary: unknown card is 404 (not an
empty 200), invalid alert_type / missing target_price / missing drop_at is 422
(client mistake, not a 500), and `active` defaults True. Filters are exact-match
(card_id, active) — the watchlist has no free-text search, so no ilike.
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
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def test_create_watch_restock(client):
    response = client.post(
        "/watchlist",
        json={"card_id": "base1-4", "alert_type": "restock"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["card_id"] == "base1-4"
    assert body["alert_type"] == "restock"
    assert body["active"] is True
    assert body["created_at"] is not None
    assert body["target_price"] is None
    assert body["drop_at"] is None


def test_create_price_target_requires_target_price(client):
    response = client.post(
        "/watchlist",
        json={"card_id": "base1-4", "alert_type": "price_target"},
    )
    assert response.status_code == 422
    assert "target_price" in response.json()["detail"].lower()


def test_create_drop_time_requires_drop_at(client):
    response = client.post(
        "/watchlist",
        json={"card_id": "base1-4", "alert_type": "drop_time"},
    )
    assert response.status_code == 422
    assert "drop_at" in response.json()["detail"].lower()


def test_create_watch_unknown_card_404(client):
    response = client.post(
        "/watchlist",
        json={"card_id": "bogus-1", "alert_type": "restock"},
    )
    assert response.status_code == 404


def test_create_watch_invalid_alert_type_422(client):
    response = client.post(
        "/watchlist",
        json={"card_id": "base1-4", "alert_type": "bogus"},
    )
    assert response.status_code == 422
    assert "alert_type" in response.json()["detail"].lower()


def test_create_price_target_with_target_succeeds(client):
    response = client.post(
        "/watchlist",
        json={
            "card_id": "base1-4",
            "alert_type": "price_target",
            "target_price": 50.0,
        },
    )
    assert response.status_code == 201
    assert response.json()["target_price"] == 50.0


def test_create_drop_time_with_drop_at_succeeds(client):
    response = client.post(
        "/watchlist",
        json={
            "card_id": "base1-4",
            "alert_type": "drop_time",
            "drop_at": "2026-08-15T18:30:00+00:00",
        },
    )
    assert response.status_code == 201
    assert response.json()["drop_at"].startswith("2026-08-15T18:30")


def test_list_watches_filter_by_card_and_active(client):
    # One active restock + one active price_target on base1-4, one inactive
    # restock on base1-58.
    r1 = client.post("/watchlist", json={"card_id": "base1-4", "alert_type": "restock"})
    r2 = client.post(
        "/watchlist",
        json={
            "card_id": "base1-4",
            "alert_type": "price_target",
            "target_price": 40.0,
        },
    )
    r3 = client.post("/watchlist", json={"card_id": "base1-58", "alert_type": "restock"})
    # Deactivate r3.
    client.patch(f"/watchlist/{r3.json()['id']}", json={"active": False})

    # No filter: all three.
    assert len(client.get("/watchlist").json()) == 3

    # card_id filter.
    by_card = client.get("/watchlist", params={"card_id": "base1-4"}).json()
    assert {w["id"] for w in by_card} == {r1.json()["id"], r2.json()["id"]}

    # active=true filter excludes the inactive one.
    active = client.get("/watchlist", params={"active": True}).json()
    assert r3.json()["id"] not in {w["id"] for w in active}
    assert len(active) == 2

    # active=false filter returns only the inactive one.
    inactive = client.get("/watchlist", params={"active": False}).json()
    assert {w["id"] for w in inactive} == {r3.json()["id"]}


def test_patch_watch(client):
    r = client.post(
        "/watchlist",
        json={
            "card_id": "base1-4",
            "alert_type": "price_target",
            "target_price": 40.0,
        },
    )
    wid = r.json()["id"]

    p1 = client.patch(f"/watchlist/{wid}", json={"active": False})
    assert p1.status_code == 200
    assert p1.json()["active"] is False
    assert p1.json()["target_price"] == 40.0

    p2 = client.patch(f"/watchlist/{wid}", json={"target_price": 25.0})
    assert p2.status_code == 200
    assert p2.json()["target_price"] == 25.0
    assert p2.json()["active"] is False

    # 404 on missing watch.
    assert client.patch("/watchlist/9999", json={"active": True}).status_code == 404


def test_delete_watch(client):
    r = client.post("/watchlist", json={"card_id": "base1-4", "alert_type": "restock"})
    wid = r.json()["id"]

    d1 = client.delete(f"/watchlist/{wid}")
    assert d1.status_code == 204

    # No longer listed.
    assert wid not in {w["id"] for w in client.get("/watchlist").json()}

    # Second delete 404s.
    assert client.delete(f"/watchlist/{wid}").status_code == 404


def test_list_newest_first(client):
    """GET /watchlist returns newest first (id desc)."""
    a = client.post("/watchlist", json={"card_id": "base1-4", "alert_type": "restock"}).json()
    b = client.post("/watchlist", json={"card_id": "base1-4", "alert_type": "restock",
                                        "variant": "holofoil"}).json()
    c = client.post("/watchlist", json={"card_id": "base1-58", "alert_type": "restock"}).json()

    ids = [w["id"] for w in client.get("/watchlist").json()]
    assert ids == [c["id"], b["id"], a["id"]]