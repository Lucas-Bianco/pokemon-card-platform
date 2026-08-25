"""Row 25: CollectionStore.portfolio_history() — reconstructed portfolio market
value over time, from append-only price snapshots.

The reconstruction holds the CURRENT set of holdings and quantities fixed and, at
each past observation, values them at the most recent price recorded at or before
that time, using the same TCGplayer-then-Cardmarket resolution ``latest_price``
uses. Unpriced holdings are excluded (counted in unpriced_items), never guessed at
$0. Empty points means no price history yet, not a $0 valuation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Gym"))
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
    return db


@pytest.fixture
def store(seeded):
    return CollectionStore(seeded)


def hold(session, card_id, variant="normal", quantity=1):
    session.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()


def snap(session, card_id, source, variant, market, fetched_at, source_updated_at=None):
    # source_updated_at defaults to a date derived from fetched_at, so two same-source
    # snapshots for one card (unique on card_id+source+variant+source_updated_at) don't
    # collide.
    if source_updated_at is None:
        source_updated_at = fetched_at.strftime("%Y/%m/%d")
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            fetched_at=fetched_at,
            source_updated_at=source_updated_at,
        )
    )
    session.commit()


def t(month, day=1):
    return datetime(2026, month, day, 12, 0, 0, tzinfo=timezone.utc)


def test_empty_collection_returns_no_points(store):
    h = store.portfolio_history()
    assert h.points == []
    assert h.total_items == 0
    assert h.priced_items == 0
    assert h.unpriced_items == 0
    assert h.caveat


def test_holdings_with_no_snapshots_return_no_points_but_count_unpriced(store, seeded):
    hold(seeded, "base1-4")
    hold(seeded, "base1-58")
    h = store.portfolio_history()
    assert h.points == []
    assert h.total_items == 2
    assert h.priced_items == 0
    assert h.unpriced_items == 2  # never $0 — honest empty, not a point at 0


def test_single_holding_single_snapshot_emits_one_point(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    h = store.portfolio_history()
    assert len(h.points) == 1
    assert h.points[0].market_value == 10.0
    assert h.points[0].priced_items == 1
    assert h.points[0].unpriced_items == 0
    assert h.points[0].observed_at == t(1)


def test_single_holding_multi_snapshots_step_timeline(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    snap(seeded, "base1-4", "tcgplayer", "normal", 25.0, t(2))
    h = store.portfolio_history()
    assert len(h.points) == 2
    assert [p.market_value for p in h.points] == [10.0, 25.0]
    assert h.points[0].observed_at == t(1)
    assert h.points[1].observed_at == t(2)


def test_tcgplayer_preferred_over_cardmarket_at_each_point(store, seeded):
    # tcg at t1=10, then a newer cardmarket at t2=20. latest_price prefers tcg by
    # source priority (not recency), so the effective price at t2 is still 10.
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    snap(seeded, "base1-4", "cardmarket", "aggregate", 20.0, t(2))
    h = store.portfolio_history()
    assert [p.market_value for p in h.points] == [10.0, 10.0]


def test_cardmarket_fallback_when_no_tcg(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "cardmarket", "aggregate", 18.0, t(1))
    snap(seeded, "base1-4", "cardmarket", "aggregate", 22.0, t(2))
    h = store.portfolio_history()
    assert [p.market_value for p in h.points] == [18.0, 22.0]


def test_tcg_then_cardmarket_then_back_to_tcg_matches_latest_price_resolution(store, seeded):
    # cm first (no tcg yet) -> effective = cm. tcg arrives -> effective = tcg. A
    # later cm must NOT displace tcg (source priority, not recency).
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "cardmarket", "aggregate", 18.0, t(1))
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(2))
    snap(seeded, "base1-4", "cardmarket", "aggregate", 99.0, t(3))
    h = store.portfolio_history()
    assert [p.market_value for p in h.points] == [18.0, 10.0, 10.0]


def test_multiple_holdings_summed_and_priced_items_grows(store, seeded):
    hold(seeded, "base1-4", quantity=2)      # Charizard
    hold(seeded, "base1-58", quantity=1)     # Pikachu
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))   # Charizard priced at t1
    snap(seeded, "base1-58", "tcgplayer", "normal", 15.0, t(2))  # Pikachu priced at t2
    h = store.portfolio_history()
    assert len(h.points) == 2
    # t1: only Charizard priced -> 10 x 2 = 20, priced 1, unpriced 1
    assert h.points[0].market_value == 20.0
    assert h.points[0].priced_items == 1
    assert h.points[0].unpriced_items == 1
    # t2: both priced -> 20 + 15 = 35, priced 2
    assert h.points[1].market_value == 35.0
    assert h.points[1].priced_items == 2
    assert h.points[1].unpriced_items == 0


def test_unpriced_holding_excluded_never_zero(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    hold(seeded, "base1-58", quantity=1)  # never gets a snapshot
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    h = store.portfolio_history()
    assert len(h.points) == 1
    assert h.points[0].market_value == 10.0  # only Charizard, never 0 for Pikachu
    assert h.points[0].priced_items == 1
    assert h.points[0].unpriced_items == 1


def test_quantity_multiplies_price(store, seeded):
    hold(seeded, "base1-4", quantity=3)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    h = store.portfolio_history()
    assert h.points[0].market_value == 30.0


def test_since_filter_emits_later_points_but_preserves_pre_since_prices(store, seeded):
    # The per-holding timeline keeps pre-since snapshots, so a holding priced
    # before the window still contributes its correct price to in-window points
    # (honest reconstruction, not a hole at $0).
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    snap(seeded, "base1-4", "tcgplayer", "normal", 25.0, t(2))
    snap(seeded, "base1-4", "tcgplayer", "normal", 40.0, t(3))
    h = store.portfolio_history(since=t(2))
    assert len(h.points) == 2
    assert [p.market_value for p in h.points] == [25.0, 40.0]
    assert h.points[0].observed_at == t(2)


def test_days_filter_equivalent_to_since(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    snap(seeded, "base1-4", "tcgplayer", "normal", 40.0, t(3))
    # days window starting just before t3 should include t3 but not t1.
    since = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - since).days
    h = store.portfolio_history(days=days)
    assert all(p.observed_at >= since for p in h.points)
    assert h.points[-1].market_value == 40.0


def test_same_fetched_at_deduped_to_one_point(store, seeded):
    # Two snapshots at the same fetched_at: one portfolio point, and the later
    # id (tcg) wins per the tcg-preferred resolution.
    hold(seeded, "base1-4", quantity=1)
    same = t(1)
    snap(seeded, "base1-4", "cardmarket", "aggregate", 18.0, same)
    snap(seeded, "base1-4", "tcgplayer", "normal", 12.0, same)
    h = store.portfolio_history()
    assert len(h.points) == 1
    assert h.points[0].market_value == 12.0  # tcg preferred at the shared time


def test_points_ordered_oldest_first(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    # Insert out of chronological order; output must still be oldest-first.
    snap(seeded, "base1-4", "tcgplayer", "normal", 40.0, t(3))
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    snap(seeded, "base1-4", "tcgplayer", "normal", 25.0, t(2))
    h = store.portfolio_history()
    assert [p.observed_at for p in h.points] == [t(1), t(2), t(3)]
    assert [p.market_value for p in h.points] == [10.0, 25.0, 40.0]


def test_reported_priced_unpriced_match_last_point(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    hold(seeded, "base1-58", quantity=1)  # unpriced throughout
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, t(1))
    h = store.portfolio_history()
    assert h.priced_items == h.points[-1].priced_items
    assert h.unpriced_items == h.points[-1].unpriced_items
    assert h.total_items == 2


def test_caveat_is_honest_about_current_holdings_and_cadence(store):
    h = store.portfolio_history()
    assert "current" in h.caveat.lower()
    assert "cadence" in h.caveat.lower()
    # The honest never-$0 promise is stated.
    assert "$0" in h.caveat or "never $0" in h.caveat.lower()