"""Unit tests for the vault importer (roadmap row 30).

Pins the pure-DB behavior: valid rows insert directly (preserving acquired_at
so the Row 27 timeline stays honest, and NOT topping-up duplicate printings
the way CollectionStore.add does), unknown cards / missing card_id / quantity
< 1 are skipped with honest reasons, optional empties are null never $0,
commit happens once, and an empty input is an honest empty report (not an
error). Mirrors test_sold_service.py's fixture style.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.collection.importer import ImportRow, import_holdings
from cardplatform.db.models import Card, CardSet, CollectionItem


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Jungle"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", rarity="Rare Holo"))
    db.add(Card(id="base2-1", set_id="base2", name="Pikachu", number="1", rarity="Common"))
    db.commit()
    return db


def test_imports_valid_rows_directly_preserving_acquired_at(seeded):
    rows = [
        ImportRow(card_id="base1-4", variant="normal", quantity=2, acquired_price=20.0,
                  acquired_at=datetime(2020, 1, 15, tzinfo=timezone.utc), condition="NM", notes="g"),
        ImportRow(card_id="base2-1", variant="reverseHolofoil", quantity=1),
    ]
    report = import_holdings(seeded, rows)
    assert report.total == 2
    assert report.added == 2
    assert report.skipped == []
    items = seeded.query(CollectionItem).order_by(CollectionItem.id).all()
    assert len(items) == 2
    assert items[0].quantity == 2
    assert items[0].acquired_price == 20.0
    assert items[0].acquired_at is not None
    assert items[0].acquired_at.year == 2020
    # Two printings stay as two rows (import never tops-up).
    assert items[1].variant == "reverseHolofoil"
    assert items[1].acquired_price is None
    assert items[1].acquired_at is None  # undated, never a fabricated epoch
    assert items[1].condition is None


def test_imports_two_dated_printings_as_two_rows(seeded):
    """The load-bearing difference from CollectionStore.add: adding the same
    (card_id, variant) twice with different acquired_at must produce two rows,
    not one topped-up row, so the acquisition timeline is accurate."""
    rows = [
        ImportRow(card_id="base1-4", quantity=1, acquired_at=datetime(2019, 1, 1, tzinfo=timezone.utc)),
        ImportRow(card_id="base1-4", quantity=1, acquired_at=datetime(2021, 6, 1, tzinfo=timezone.utc)),
    ]
    report = import_holdings(seeded, rows)
    assert report.added == 2
    items = seeded.query(CollectionItem).order_by(CollectionItem.id).all()
    assert len(items) == 2
    assert items[0].acquired_at.year == 2019
    assert items[1].acquired_at.year == 2021


def test_skips_unknown_card_with_reason(seeded):
    rows = [ImportRow(card_id="base1-4", quantity=1), ImportRow(card_id="nope", quantity=1)]
    report = import_holdings(seeded, rows)
    assert report.added == 1
    assert len(report.skipped) == 1
    skip = report.skipped[0]
    assert skip.row_number == 2
    assert skip.card_id == "nope"
    assert "unknown card" in skip.reason


def test_skips_missing_card_id(seeded):
    rows = [ImportRow(card_id="", quantity=1), ImportRow(card_id="   ", quantity=1)]
    report = import_holdings(seeded, rows)
    assert report.added == 0
    assert len(report.skipped) == 2
    assert all(s.card_id is None for s in report.skipped)
    assert all("missing card id" in s.reason for s in report.skipped)


def test_skips_quantity_below_one(seeded):
    rows = [ImportRow(card_id="base1-4", quantity=0)]
    report = import_holdings(seeded, rows)
    assert report.added == 0
    assert len(report.skipped) == 1
    assert "quantity" in report.skipped[0].reason
    assert report.skipped[0].card_id == "base1-4"


def test_blank_variant_falls_back_to_normal(seeded):
    rows = [ImportRow(card_id="base1-4", variant="", quantity=1)]
    report = import_holdings(seeded, rows)
    assert report.added == 1
    assert seeded.query(CollectionItem).one().variant == "normal"


def test_empty_input_is_empty_report(seeded):
    report = import_holdings(seeded, [])
    assert report.total == 0
    assert report.added == 0
    assert report.skipped == []
    assert report.caveat


def test_report_caveat_is_honest_about_what_skips_and_preserves(seeded):
    report = import_holdings(seeded, [ImportRow(card_id="base1-4", quantity=1)])
    assert "acquired_at" in report.caveat
    assert "skipped" in report.caveat.lower()