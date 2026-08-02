"""T5: Web Push subscription HTTP endpoints — upsert by endpoint, vapid public
key, unsubscribe.

Pins the upsert contract: the same endpoint re-subscribing updates p256dh/auth
(keys rotate) rather than inserting a second row. `vapid_public_key` surfaces as
an empty string when not configured (honest; the frontend checks for emptiness).
Unsubscribe 404s on an unknown endpoint, matching the watchlist DELETE style.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet, PushSubscription


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def test_subscribe_upsert(seeded, client):
    payload = {"endpoint": "https://fcm/google/s/abc", "p256dh": "key1", "auth": "a1"}
    r1 = client.post("/push/subscribe", json=payload)
    assert r1.status_code == 201
    assert r1.json()["endpoint"] == "https://fcm/google/s/abc"

    # Same endpoint, rotated keys -> upsert, not a second row.
    payload2 = {"endpoint": "https://fcm/google/s/abc", "p256dh": "key2", "auth": "a2"}
    r2 = client.post("/push/subscribe", json=payload2)
    assert r2.status_code in (200, 201)
    assert r2.json()["endpoint"] == "https://fcm/google/s/abc"

    rows = seeded.query(PushSubscription).all()
    assert len(rows) == 1
    assert rows[0].p256dh == "key2"
    assert rows[0].auth == "a2"


def test_vapid_public_unconfigured(client):
    """Default settings have no vapid key -> empty string (frontend checks for
    emptiness, not None)."""
    response = client.get("/push/vapid-public")
    assert response.status_code == 200
    assert response.json() == {"public_key": ""}


def test_unsubscribe(seeded, client):
    client.post(
        "/push/subscribe",
        json={"endpoint": "https://fcm/google/s/xyz", "p256dh": "k", "auth": "a"},
    )

    d1 = client.delete("/push/subscribe", params={"endpoint": "https://fcm/google/s/xyz"})
    assert d1.status_code == 204

    # Row gone.
    assert seeded.query(PushSubscription).count() == 0

    # Second delete 404s.
    d2 = client.delete("/push/subscribe", params={"endpoint": "https://fcm/google/s/xyz"})
    assert d2.status_code == 404


def test_subscribe_new_endpoint_inserts(seeded, client):
    """Two distinct endpoints -> two rows."""
    client.post("/push/subscribe",
                json={"endpoint": "https://e/1", "p256dh": "k", "auth": "a"})
    client.post("/push/subscribe",
                json={"endpoint": "https://e/2", "p256dh": "k", "auth": "a"})
    assert seeded.query(PushSubscription).count() == 2