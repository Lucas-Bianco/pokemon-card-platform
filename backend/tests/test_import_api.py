"""HTTP boundary tests for the vault import (roadmap row 30).

Pins the wire contract for POST /collection/import?format=csv|json: valid rows
become holdings (preserving acquired_at so the Row 27 timeline stays honest),
rows whose card_id isn't in the catalog are skipped with an honest reason
(never silently dropped or coerced), rows missing card_id or with quantity < 1
are skipped with a reason, optional empty fields are null (never a fabricated
$0), an over-cap file is 400 before any write, and the literal /collection/import
route is not shadowed by the parametric PATCH /collection/{item_id}.

Mirrors test_sold_api.py: direct inserts + a dependency override for get_session.
"""
from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem


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


def _post_csv(client, rows: list[dict], header: list[str] | None = None):
    cols = header or ["card_id", "variant", "quantity", "condition", "acquired_price", "acquired_at", "notes"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return client.post(
        "/collection/import?format=csv",
        content=buf.getvalue(),
        headers={"Content-Type": "text/plain"},
    )


def _post_json(client, items: list[dict]):
    return client.post(
        "/collection/import?format=json",
        content=json.dumps({"items": items}),
        headers={"Content-Type": "text/plain"},
    )


def test_import_csv_adds_holdings_and_preserves_acquired_at(client, seeded):
    r = _post_csv(client, [
        {"card_id": "base1-4", "variant": "normal", "quantity": "2", "acquired_price": "20", "acquired_at": "2020-01-15T00:00:00Z", "condition": "NM", "notes": "graded"},
        {"card_id": "base2-1", "variant": "reverseHolofoil", "quantity": "1", "acquired_price": "", "acquired_at": "", "condition": "", "notes": ""},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["added"] == 2
    assert body["skipped"] == []
    assert body["caveat"]
    # Rows inserted directly with the imported acquired_at preserved (not now).
    rows = seeded.query(CollectionItem).order_by(CollectionItem.id).all()
    assert len(rows) == 2
    zard = next(r for r in rows if r.card_id == "base1-4")
    assert zard.quantity == 2
    assert zard.acquired_price == 20.0
    assert zard.condition == "NM"
    assert zard.notes == "graded"
    assert zard.acquired_at is not None
    assert zard.acquired_at.year == 2020 and zard.acquired_at.month == 1 and zard.acquired_at.day == 15
    # Two distinct printings, not topped-up into one row.
    pika = next(r for r in rows if r.card_id == "base2-1")
    assert pika.variant == "reverseHolofoil"
    assert pika.acquired_price is None
    assert pika.acquired_at is None  # blank -> undated, never a fabricated epoch
    assert pika.condition is None


def test_import_skips_unknown_card_with_reason(client, seeded):
    r = _post_csv(client, [
        {"card_id": "base1-4", "quantity": "1"},
        {"card_id": "does-not-exist", "quantity": "1"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["added"] == 1
    assert len(body["skipped"]) == 1
    skip = body["skipped"][0]
    assert skip["row_number"] == 2
    assert skip["card_id"] == "does-not-exist"
    assert "unknown card" in skip["reason"]


def test_import_skips_missing_card_id(client):
    r = _post_csv(client, [
        {"card_id": "", "quantity": "1"},
        {"card_id": "base1-4", "quantity": "1"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["row_number"] == 1
    assert body["skipped"][0]["card_id"] is None
    assert "missing card id" in body["skipped"][0]["reason"]


def test_import_skips_quantity_below_one(client):
    r = _post_csv(client, [
        {"card_id": "base1-4", "quantity": "0"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 0
    assert len(body["skipped"]) == 1
    assert "quantity" in body["skipped"][0]["reason"]
    assert body["skipped"][0]["card_id"] == "base1-4"


def test_import_quantity_blank_defaults_to_one(client, seeded):
    r = _post_csv(client, [{"card_id": "base1-4"}])
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    assert seeded.query(CollectionItem).one().quantity == 1


def test_import_json_round_trips_export(client, seeded):
    items = [
        {"card_id": "base1-4", "variant": "normal", "quantity": 3, "acquired_price": 15.5, "acquired_at": "2021-06-01T00:00:00Z"},
        {"card_id": "base2-1", "variant": "normal", "quantity": 1, "acquired_price": None, "acquired_at": None},
    ]
    r = _post_json(client, items)
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 2
    assert body["skipped"] == []
    rows = seeded.query(CollectionItem).order_by(CollectionItem.id).all()
    assert len(rows) == 2
    assert rows[0].quantity == 3
    assert rows[0].acquired_price == 15.5
    assert rows[0].acquired_at is not None and rows[0].acquired_at.year == 2021


def test_import_json_skips_unknown_card(client, seeded):
    r = _post_json(client, [
        {"card_id": "base1-4", "quantity": 1},
        {"card_id": "nope", "quantity": 1},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    assert body["skipped"][0]["card_id"] == "nope"
    assert "unknown card" in body["skipped"][0]["reason"]


def test_import_json_rejects_non_list_items(client):
    r = client.post(
        "/collection/import?format=json",
        content=json.dumps({"items": "not a list"}),
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 400
    assert "items" in r.json()["detail"]


def test_import_invalid_json_returns_400(client):
    r = client.post(
        "/collection/import?format=json",
        content="{not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 400


def test_import_over_cap_returns_400_before_any_write(client, seeded):
    rows = [{"card_id": "base1-4", "quantity": "1"} for _ in range(10001)]
    r = _post_csv(client, rows)
    assert r.status_code == 400
    assert "row" in r.json()["detail"].lower()
    # Nothing was written.
    assert seeded.query(CollectionItem).count() == 0


def test_import_route_not_shadowed_by_parametric_patch(client, seeded):
    """The literal POST /collection/import must reach the import handler, not be
    captured by any parametric /collection/{...} route. A 200 + a real inserted
    holding proves the literal handler ran; a parametric route would 422 on the
    non-int 'import' path segment and never insert."""
    r = _post_csv(client, [{"card_id": "base1-4", "quantity": "1"}])
    assert r.status_code == 200
    assert r.json()["added"] == 1
    assert seeded.query(CollectionItem).count() == 1


def test_import_tolerates_header_case_and_extra_columns(client, seeded):
    """An export tweaked by a spreadsheet (uppercase headers, extra computed
    columns) still round-trips; computed columns are ignored, not required."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Card_Id", "Variant", "Quantity", "Condition", "Acquired_Price", "Acquired_At", "Market_Price", "Priced", "Notes"])
    w.writerow(["base1-4", "normal", "1", "NM", "10", "2019-09-09T00:00:00Z", "999.00", "yes", "x"])
    r = client.post(
        "/collection/import?format=csv",
        content=buf.getvalue(),
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    row = seeded.query(CollectionItem).one()
    assert row.acquired_price == 10.0
    assert row.acquired_at is not None and row.acquired_at.year == 2019