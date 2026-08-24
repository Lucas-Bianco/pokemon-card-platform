"""Phase 18: CollectionStore.insurance_value() — replacement-value bands for
insurance, from the same proven price snapshot the rest of the app uses.

conservative = low (fallback to market when low is missing)
median       = market
aggressive   = high (fallback to market when high is missing)

Unpriced cards (no snapshot / market is None) are EXCLUDED from the three totals
and counted in unpriced_items — never guessed at $0. Every schedule line carries
its own source + source_updated_at (the "" sentinel coerced to None), so a printed
schedule never presents a number without saying where it came from.
"""
from __future__ import annotations

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.add(Card(id="base1-7", set_id="base1", name="Clefairy", number="7"))
    db.commit()
    return db


@pytest.fixture
def store(seeded):
    return CollectionStore(seeded)


def snap(session, card_id, source, variant, market, low=None, mid=None, high=None,
         source_updated_at="2026/07/28"):
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            low=low,
            mid=mid,
            high=high,
            market=market,
            source_updated_at=source_updated_at,
        )
    )
    session.commit()


def test_empty_collection_is_all_zero_bands_and_zero_items(store):
    v = store.insurance_value()
    assert v.conservative == 0.0
    assert v.median == 0.0
    assert v.aggressive == 0.0
    assert v.priced_items == 0
    assert v.unpriced_items == 0
    assert v.schedule == []
    assert v.caveat  # never empty


def test_priced_holding_sums_into_three_bands_with_low_market_high(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0, low=90.0, mid=100.0, high=120.0)
    store.add("base1-4", variant="normal", quantity=2)

    v = store.insurance_value()
    # conservative = low (90) * 2 = 180; median = market (100) * 2 = 200; aggressive = high (120) * 2 = 240
    assert v.conservative == 180.0
    assert v.median == 200.0
    assert v.aggressive == 240.0
    assert v.priced_items == 1
    assert v.unpriced_items == 0


def test_low_missing_falls_back_to_market_for_conservative(store, seeded):
    # Only market present, no low/high — conservative and aggressive both fall back to market.
    snap(seeded, "base1-58", "tcgplayer", "normal", market=50.0)
    store.add("base1-58", variant="normal", quantity=1)

    v = store.insurance_value()
    assert v.conservative == 50.0  # low missing -> market
    assert v.median == 50.0
    assert v.aggressive == 50.0  # high missing -> market


def test_unpriced_holding_excluded_from_totals_and_counted(store, seeded):
    # base1-4 priced, base1-58 unpriced (no snapshot), base1-7 unpriced (snapshot with market None)
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0, low=90.0, high=120.0)
    snap(seeded, "base1-7", "tcgplayer", "normal", market=None, low=None, high=None)
    store.add("base1-4", variant="normal", quantity=1)
    store.add("base1-58", variant="normal", quantity=3)
    store.add("base1-7", variant="normal", quantity=1)

    v = store.insurance_value()
    assert v.conservative == 90.0  # only base1-4
    assert v.median == 100.0
    assert v.aggressive == 120.0
    assert v.priced_items == 1
    assert v.unpriced_items == 2


def test_schedule_lists_every_holding_with_priced_flag_and_source(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0, low=90.0, mid=100.0, high=120.0,
         source_updated_at="2026/07/28")
    store.add("base1-4", variant="normal", quantity=2)
    store.add("base1-58", variant="normal", quantity=1)  # unpriced

    schedule = store.insurance_value().schedule
    assert len(schedule) == 2

    priced = next(s for s in schedule if s.card_id == "base1-4")
    assert priced.card_name == "Charizard"
    assert priced.set_name == "Base"
    assert priced.variant == "normal"
    assert priced.quantity == 2
    assert priced.low == 90.0
    assert priced.market == 100.0
    assert priced.high == 120.0
    assert priced.source == "tcgplayer"
    assert priced.source_updated_at == "2026/07/28"
    assert priced.priced is True

    unpriced = next(s for s in schedule if s.card_id == "base1-58")
    assert unpriced.market is None
    assert unpriced.low is None
    assert unpriced.high is None
    assert unpriced.source is None
    assert unpriced.source_updated_at is None
    assert unpriced.priced is False


def test_empty_string_source_updated_at_coerced_to_none_on_the_wire(store, seeded):
    # The "" sentinel (used so NULLs don't defeat uq_snapshot) must surface as None,
    # never as an empty string, on the schedule.
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0, source_updated_at="")
    store.add("base1-4", variant="normal", quantity=1)

    line = store.insurance_value().schedule[0]
    assert line.source_updated_at is None
    assert line.source == "tcgplayer"


def test_cardmarket_fallback_snapshot_is_used_when_tcgplayer_absent(store, seeded):
    # latest_price prefers tcgplayer then cardmarket/aggregate. A cardmarket-only
    # snapshot still prices the holding; its source surfaces on the schedule.
    snap(seeded, "base1-4", "cardmarket", "aggregate", market=80.0, low=70.0, high=95.0)
    store.add("base1-4", variant="normal", quantity=2)

    v = store.insurance_value()
    assert v.median == 160.0  # 80 * 2
    assert v.conservative == 140.0  # 70 * 2
    assert v.aggressive == 190.0  # 95 * 2
    line = v.schedule[0]
    assert line.source == "cardmarket"
    assert line.priced is True


def test_variant_specific_snapshot_used(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "holofoil", market=200.0, low=180.0, high=240.0)
    store.add("base1-4", variant="holofoil", quantity=1)
    store.add("base1-4", variant="normal", quantity=1)  # no normal snapshot -> unpriced

    v = store.insurance_value()
    assert v.median == 200.0  # only the holofoil holding priced
    assert v.priced_items == 1
    assert v.unpriced_items == 1