"""T5: alerts HTTP endpoints — the in-app notification feed over `AlertEvent`.

Pins the feed contract: newest first, unread filter, mark-read, read-all,
unread-count. AlertEvents are inserted directly (the engine fires them in T3;
this layer only reads/updates `read_at`), with controlled `created_at` to pin
the newest-first ordering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import AlertEvent, Card, CardSet


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


def _event(db, *, created_at, read_at=None, alert_type="restock", message="m"):
    db.add(
        AlertEvent(
            card_id="base1-4",
            alert_type=alert_type,
            message=message,
            context=None,
            delivered_inapp=True,
            delivered_push=False,
            delivered_email=False,
            read_at=read_at,
            created_at=created_at,
        )
    )
    db.commit()
    return db.query(AlertEvent).order_by(AlertEvent.id.desc()).first()


def test_list_alerts_newest_first(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    a = _event(seeded, created_at=t0, message="oldest")
    b = _event(seeded, created_at=t0 + timedelta(minutes=1), message="mid")
    c = _event(seeded, created_at=t0 + timedelta(minutes=2), message="newest")

    body = client.get("/alerts").json()
    assert [e["id"] for e in body] == [c.id, b.id, a.id]


def test_list_alerts_unread_filter(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    read_one = _event(seeded, created_at=t0, read_at=t0)
    unread_one = _event(seeded, created_at=t0 + timedelta(minutes=1), read_at=None)

    all_alerts = client.get("/alerts").json()
    assert {e["id"] for e in all_alerts} == {read_one.id, unread_one.id}

    unread = client.get("/alerts", params={"unread": True}).json()
    assert {e["id"] for e in unread} == {unread_one.id}
    assert all(e["read_at"] is None for e in unread)


def test_mark_alert_read(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    e = _event(seeded, created_at=t0, read_at=None)

    response = client.patch(f"/alerts/{e.id}")
    assert response.status_code == 200
    assert response.json()["read_at"] is not None

    # Persisted.
    seeded.refresh(e)
    assert e.read_at is not None

    # 404 on missing.
    assert client.patch("/alerts/9999").status_code == 404


def test_read_all(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    a = _event(seeded, created_at=t0, read_at=None)
    b = _event(seeded, created_at=t0 + timedelta(minutes=1), read_at=None)
    c = _event(seeded, created_at=t0 + timedelta(minutes=2), read_at=t0)  # already read

    response = client.post("/alerts/read-all")
    assert response.status_code == 200
    assert response.json() == {"updated": 2}

    # All unread are now read.
    assert client.get("/alerts/unread-count").json() == {"count": 0}


def test_unread_count(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    _event(seeded, created_at=t0, read_at=None)
    _event(seeded, created_at=t0 + timedelta(minutes=1), read_at=None)
    _event(seeded, created_at=t0 + timedelta(minutes=2), read_at=t0)

    assert client.get("/alerts/unread-count").json() == {"count": 2}


def test_alerts_pagination(seeded, client):
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _event(seeded, created_at=t0 + timedelta(minutes=i))

    full = client.get("/alerts").json()
    page = client.get("/alerts", params={"limit": 2, "offset": 0}).json()
    assert len(page) == 2

    page2 = client.get("/alerts", params={"limit": 2, "offset": 2}).json()
    assert len(page2) == 2

    # The two pages cover the first four of the full newest-first list, in order.
    assert [e["id"] for e in page + page2] == [e["id"] for e in full[:4]]