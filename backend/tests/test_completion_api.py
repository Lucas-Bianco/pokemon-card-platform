"""Tests for GET /sets + GET /sets/{id} (Phase 06)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09", total=2))
    db.add(Card(id="base1-1", set_id="base1", name="Bulbasaur", number="1"))
    db.add(Card(id="base1-2", set_id="base1", name="Ivysaur", number="2"))
    db.add(CollectionItem(card_id="base1-1", variant="normal", quantity=1))
    db.commit()
    # Snapshot in its own commit so the card FK row exists first (mirrors
    # test_completion.py's snap() helper).
    db.add(
        PriceSnapshot(
            card_id="base1-2",
            source="tcgplayer",
            variant="normal",
            market=3.0,
            source_updated_at="2026/07/28",
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


def test_get_sets_returns_progress(client):
    r = client.get("/sets")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == "base1"
    assert body[0]["owned"] == 1
    assert body[0]["checklist_size"] == 2
    assert body[0]["pct_complete"] == 0.5


def test_get_sets_q_filter(client):
    r = client.get("/sets?q=bas")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == ["base1"]


def test_get_sets_whitespace_q_is_422(client):
    r = client.get("/sets?q=%20%20")  # whitespace-only
    assert r.status_code == 422


def test_get_sets_limit_out_of_range_is_422(client):
    assert client.get("/sets?limit=0").status_code == 422
    assert client.get("/sets?limit=201").status_code == 422


def test_get_set_detail(client):
    r = client.get("/sets/base1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "base1"
    by_id = {c["card_id"]: c for c in body["cards"]}
    assert by_id["base1-1"]["owned"] is True
    assert by_id["base1-2"]["owned"] is False
    assert by_id["base1-2"]["market"] == 3.0
    assert body["summary"]["owned"] == 1
    assert body["summary"]["missing"] == 1
    assert body["summary"]["est_cost_to_complete"] == 3.0
    assert body["summary"]["unpriced_missing"] == 0


def test_get_set_detail_unknown_is_404(client):
    r = client.get("/sets/nope")
    assert r.status_code == 404