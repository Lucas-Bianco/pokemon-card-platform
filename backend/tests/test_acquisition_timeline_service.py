"""Row 27: CollectionStore.acquisition_timeline() — the collection's growth over
time, cumulative card count + cumulative cost basis at each distinct holding
acquired_at, oldest-first. acquired_at is always set on add (defaults to now), so
the card line is always populated; the cost line sums only holdings with a
recorded purchase price, so unpriced acquisitions raise the card line only, never
a fabricated $0 cost line. Undated holdings (acquired_at None) are excluded and
counted separately, never a point at time zero. Empty = no points.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, CollectionItem


@pytest.fixture
def seeded(db):
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
    return db


@pytest.fixture
def store(seeded):
    return CollectionStore(seeded)


def hold(session, card_id, variant="normal", quantity=1, acquired_price=None, acquired_at=None):
    session.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_price=acquired_price, acquired_at=acquired_at,
        )
    )
    session.commit()


def t(month, day=1, hour=12):
    return datetime(2026, month, day, hour, 0, 0, tzinfo=timezone.utc)


def test_empty_collection_has_no_points_never_a_zero_point(store):
    tl = store.acquisition_timeline()
    assert tl.points == []
    assert tl.total_holdings == 0
    assert tl.total_cards == 0
    assert tl.total_cost_basis == 0.0
    assert tl.holdings_with_cost == 0
    assert tl.holdings_without_cost == 0
    assert tl.undated_holdings == 0
    assert tl.caveat


def test_single_holding_one_point_with_cumulative_cards_and_cost(store, seeded):
    hold(seeded, "base1-4", quantity=2, acquired_price=10.0, acquired_at=t(1))
    tl = store.acquisition_timeline()
    assert len(tl.points) == 1
    p = tl.points[0]
    assert p.cumulative_cards == 2
    assert p.cumulative_cost_basis == 20.0
    assert p.observed_at == t(1)
    assert tl.total_cards == 2
    assert tl.total_cost_basis == 20.0
    assert tl.holdings_with_cost == 1


def test_multiple_holdings_cumulate_oldest_first(store, seeded):
    hold(seeded, "base1-4", quantity=1, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-58", quantity=3, acquired_price=5.0, acquired_at=t(2))
    tl = store.acquisition_timeline()
    assert [p.observed_at for p in tl.points] == [t(1), t(2)]
    assert [p.cumulative_cards for p in tl.points] == [1, 4]      # 1, then 1+3
    assert [p.cumulative_cost_basis for p in tl.points] == [10.0, 25.0]  # 10, then 10+15


def test_unpriced_acquisition_raises_card_line_only_never_zero_cost(store, seeded):
    # A holding with no purchase price contributes to the card line but NOT the
    # cost line — never a fabricated $0 cost.
    hold(seeded, "base1-4", quantity=2, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-58", quantity=3, acquired_price=None, acquired_at=t(2))
    tl = store.acquisition_timeline()
    assert [p.cumulative_cards for p in tl.points] == [2, 5]
    assert [p.cumulative_cost_basis for p in tl.points] == [20.0, 20.0]  # flat, not 20+0
    assert tl.holdings_with_cost == 1
    assert tl.holdings_without_cost == 1
    assert tl.total_cost_basis == 20.0


def test_quantity_multiplies_cost_contribution(store, seeded):
    hold(seeded, "base1-4", quantity=4, acquired_price=7.5, acquired_at=t(1))
    tl = store.acquisition_timeline()
    assert tl.points[0].cumulative_cost_basis == 30.0  # 7.5 x 4
    assert tl.total_cards == 4


def test_same_acquired_at_collapses_to_one_point(store, seeded):
    hold(seeded, "base1-4", quantity=1, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-58", quantity=2, acquired_price=3.0, acquired_at=t(1))
    tl = store.acquisition_timeline()
    assert len(tl.points) == 1
    assert tl.points[0].cumulative_cards == 3
    assert tl.points[0].cumulative_cost_basis == 16.0


def test_undated_holdings_excluded_counted_separately_never_time_zero(store, seeded):
    hold(seeded, "base1-4", quantity=1, acquired_price=10.0, acquired_at=t(2))
    hold(seeded, "base1-58", quantity=2, acquired_price=None, acquired_at=None)  # undated
    tl = store.acquisition_timeline()
    # Only the dated holding produces a point — never a fabricated point at "time zero".
    assert [p.observed_at for p in tl.points] == [t(2)]
    assert tl.points[0].cumulative_cards == 1
    assert tl.undated_holdings == 1
    assert tl.total_holdings == 2
    assert tl.total_cards == 3  # undated still counts toward total cards


def test_all_undated_collection_has_no_points_but_counts_undated(store, seeded):
    hold(seeded, "base1-4", quantity=1, acquired_at=None)
    hold(seeded, "base1-58", quantity=2, acquired_at=None)
    tl = store.acquisition_timeline()
    assert tl.points == []
    assert tl.undated_holdings == 2
    assert tl.total_holdings == 2
    assert tl.total_cards == 3


def test_out_of_order_inserts_are_sorted_oldest_first(store, seeded):
    # Insert newest first; timeline must still emit oldest-first.
    hold(seeded, "base1-58", quantity=1, acquired_price=5.0, acquired_at=t(3))
    hold(seeded, "base1-4", quantity=1, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-4", variant="holofoil", quantity=1, acquired_price=20.0, acquired_at=t(2))
    tl = store.acquisition_timeline()
    assert [p.observed_at for p in tl.points] == [t(1), t(2), t(3)]
    assert [p.cumulative_cards for p in tl.points] == [1, 2, 3]
    assert [p.cumulative_cost_basis for p in tl.points] == [10.0, 30.0, 35.0]


def test_total_cards_and_cost_basis_match_summed_holdings(store, seeded):
    hold(seeded, "base1-4", quantity=2, acquired_price=10.0, acquired_at=t(1))   # 20 cost
    hold(seeded, "base1-58", quantity=3, acquired_price=4.0, acquired_at=t(2))   # 12 cost
    hold(seeded, "base1-4", variant="holofoil", quantity=1, acquired_price=None, acquired_at=t(3))
    tl = store.acquisition_timeline()
    assert tl.total_cards == 6
    assert tl.total_cost_basis == 32.0
    assert tl.holdings_with_cost == 2
    assert tl.holdings_without_cost == 1


def test_last_point_matches_totals(store, seeded):
    hold(seeded, "base1-4", quantity=2, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-58", quantity=1, acquired_price=15.0, acquired_at=t(2))
    tl = store.acquisition_timeline()
    last = tl.points[-1]
    assert last.cumulative_cards == tl.total_cards
    assert last.cumulative_cost_basis == tl.total_cost_basis


def test_caveat_is_honest_about_cost_and_undated_and_never_zero(store):
    tl = store.acquisition_timeline()
    c = tl.caveat.lower()
    assert "acquired_at" in c
    assert "purchase price" in c or "cost" in c
    assert "$0" in tl.caveat or "never" in c


def test_card_line_grows_with_unpriced_acquisitions_after_priced(store, seeded):
    # Card line keeps growing through unpriced acquisitions; cost line flat.
    hold(seeded, "base1-4", quantity=1, acquired_price=10.0, acquired_at=t(1))
    hold(seeded, "base1-58", quantity=1, acquired_price=None, acquired_at=t(2))
    hold(seeded, "base1-4", variant="holofoil", quantity=1, acquired_price=None, acquired_at=t(3))
    tl = store.acquisition_timeline()
    assert [p.cumulative_cards for p in tl.points] == [1, 2, 3]
    assert [p.cumulative_cost_basis for p in tl.points] == [10.0, 10.0, 10.0]