"""Row 28 API: GET /collection/export?format=csv|json — full holding schedule
export. Reuses the same portfolio() + _portfolio_item_out serialization the Vault
renders, so the export and the app can never disagree on a price. Honest: an
unpriced holding exports with a blank market-price cell / null JSON field and no
source — never a fabricated $0.00. Registered literally before the parametric
PATCH /collection/{item_id} so the word "export" isn't captured as an item_id.
"""
from __future__ import annotations

import csv
import io as _io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


@pytest.fixture
def client(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
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
    db.commit()
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _db():
    return app.dependency_overrides[get_session]()


def _hold(card_id, variant="normal", quantity=1, acquired_price=None, acquired_at=None, condition=None, notes=None):
    db = _db()
    db.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_price=acquired_price,
            acquired_at=acquired_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
            condition=condition, notes=notes,
        )
    )
    db.commit()


def _snap(card_id, source, variant, market, fetched_at, source_updated_at=None):
    db = _db()
    if source_updated_at is None:
        source_updated_at = fetched_at.strftime("%Y/%m/%d")
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant, market=market,
            fetched_at=fetched_at, source_updated_at=source_updated_at,
        )
    )
    db.commit()


EXPECTED_COLUMNS = [
    "id", "card_name", "set_name", "set_id", "card_id", "variant", "quantity",
    "condition", "acquired_price", "acquired_at", "market_price",
    "market_source", "market_source_updated_at", "unrealized", "priced", "notes",
]


def _parse_csv(text):
    reader = csv.reader(_io.StringIO(text))
    rows = list(reader)
    return rows


def test_export_empty_collection_csv_is_header_only_never_zero(client):
    r = client.get("/collection/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="vault-export.csv"' in r.headers["content-disposition"]
    rows = _parse_csv(r.text)
    assert rows[0] == EXPECTED_COLUMNS
    assert len(rows) == 1  # header only, no holdings


def test_export_empty_collection_json_shape_and_caveat(client):
    r = client.get("/collection/export?format=json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="vault-export.json"' in r.headers["content-disposition"]
    body = r.json()
    assert body["items"] == []
    assert "summary" in body
    assert body["summary"]["market_value"] == 0.0
    assert body["caveat"]
    assert "never $0" in body["caveat"]


def test_export_unpriced_holding_blank_market_cell_never_zero(client):
    _hold("base1-4", acquired_price=50.0)
    r = client.get("/collection/export?format=csv")
    rows = _parse_csv(r.text)
    assert len(rows) == 2  # header + one holding
    row = dict(zip(rows[0], rows[1]))
    assert row["market_price"] == ""           # blank, never "0.00"
    assert row["market_source"] == ""
    assert row["market_source_updated_at"] == ""
    assert row["unrealized"] == ""             # no market → no unrealized
    assert row["priced"] == "no"
    assert row["acquired_price"] == "50.00"    # cost is known


def test_export_unpriced_holding_json_null_fields(client):
    _hold("base1-4", acquired_price=50.0)
    r = client.get("/collection/export?format=json")
    body = r.json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["market_price"] is None
    assert it["market_source"] is None
    assert it["market_source_updated_at"] is None
    assert it["unrealized"] is None
    assert it["priced"] is False
    assert it["acquired_price"] == 50.0


def test_export_priced_holding_carries_market_source_and_unrealized(client):
    fetched = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
    _hold("base1-4", variant="holofoil", quantity=1, acquired_price=200.0)
    _snap("base1-4", "tcgplayer", "holofoil", 250.0, fetched, "2026/07/29")
    r = client.get("/collection/export?format=csv")
    rows = _parse_csv(r.text)
    row = dict(zip(rows[0], rows[1]))
    assert row["market_price"] == "250.00"
    assert row["market_source"] == "tcgplayer"
    assert row["market_source_updated_at"] == "2026/07/29"
    assert row["unrealized"] == "50.00"        # (250 - 200) * 1
    assert row["priced"] == "yes"
    assert row["acquired_price"] == "200.00"
    assert row["acquired_at"].startswith("2026-01-01")


def test_export_mixed_priced_and_unpriced_csv(client):
    fetched = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
    _hold("base1-4", variant="holofoil", quantity=1, acquired_price=200.0)
    _snap("base1-4", "tcgplayer", "holofoil", 250.0, fetched, "2026/07/29")
    _hold("base1-58", acquired_price=None)  # unpriced, no cost
    r = client.get("/collection/export?format=csv")
    rows = _parse_csv(r.text)
    assert len(rows) == 3  # header + two holdings
    by_card = {dict(zip(rows[0], r))["card_name"]: dict(zip(rows[0], r)) for r in rows[1:]}
    assert by_card["Charizard"]["market_price"] == "250.00"
    assert by_card["Pikachu"]["market_price"] == ""       # blank never zero
    assert by_card["Pikachu"]["acquired_price"] == ""     # no cost either


def test_export_csv_column_order(client):
    _hold("base1-4")
    r = client.get("/collection/export?format=csv")
    rows = _parse_csv(r.text)
    assert rows[0] == EXPECTED_COLUMNS


def test_export_csv_escapes_commas_in_card_name(client):
    db = _db()
    db.add(
        Card(
            id="base1-99", set_id="base1", name="Eevee, the", number="99",
            rarity="Common", supertype="Pokemon",
        )
    )
    db.commit()
    _hold("base1-99")
    r = client.get("/collection/export?format=csv")
    rows = _parse_csv(r.text)
    assert len(rows) == 2
    row = dict(zip(rows[0], rows[1]))
    assert row["card_name"] == "Eevee, the"   # quoted by csv.writer, parsed back


def test_export_default_format_is_csv(client):
    r = client.get("/collection/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


def test_export_invalid_format_rejected(client):
    r = client.get("/collection/export?format=xml")
    assert r.status_code == 422  # Query pattern validation


def test_export_json_summary_matches_portfolio(client):
    fetched = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
    _hold("base1-4", variant="holofoil", quantity=1, acquired_price=200.0)
    _snap("base1-4", "tcgplayer", "holofoil", 250.0, fetched, "2026/07/29")
    r = client.get("/collection/export?format=json")
    summary = r.json()["summary"]
    # Cross-check against the live portfolio endpoint — they must agree.
    pr = client.get("/collection/portfolio").json()["summary"]
    assert summary["market_value"] == pr["market_value"]
    assert summary["cost_basis"] == pr["cost_basis"]
    assert summary["priced_items"] == pr["priced_items"]
    assert summary["unpriced_items"] == pr["unpriced_items"]


def test_export_route_does_not_shadow_portfolio_or_patch(client):
    # /collection/export is registered before the parametric PATCH /{item_id};
    # GET /collection/portfolio and PATCH /collection/{item_id} must still resolve.
    assert client.get("/collection/portfolio").status_code == 200
    _hold("base1-4", acquired_price=10.0)
    rows = _parse_csv(client.get("/collection/export?format=csv").text)
    item_id = dict(zip(rows[0], rows[1]))["id"]
    r = client.patch(
        f"/collection/{item_id}",
        json={"acquired_price": 25.0, "acquired_at": "2026-02-02T00:00:00Z",
              "condition": "near-mint", "notes": "backfilled"},
    )
    assert r.status_code == 200
    assert r.json()["acquired_price"] == 25.0