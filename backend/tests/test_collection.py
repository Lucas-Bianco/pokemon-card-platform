from datetime import datetime, timezone

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    return db


@pytest.fixture
def store(seeded):
    return CollectionStore(seeded)


def snapshot(session, card_id, source, variant, market, source_updated_at="2026/07/28"):
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            source_updated_at=source_updated_at,
        )
    )
    session.commit()


def test_add_creates_item_and_list_items_returns_it(store):
    item = store.add("base1-4", variant="holofoil", quantity=3, acquired_price=60.0)

    assert item.card_id == "base1-4"
    assert item.variant == "holofoil"
    assert item.quantity == 3
    assert store.list_items() == [item]


def test_adding_same_card_and_variant_twice_increments_one_row(store):
    store.add("base1-4", variant="holofoil", quantity=2)
    store.add("base1-4", variant="holofoil", quantity=3)

    items = store.list_items()
    assert len(items) == 1
    assert items[0].quantity == 5


def test_different_variants_of_same_card_are_separate_rows(store):
    store.add("base1-4", variant="holofoil", quantity=1)
    store.add("base1-4", variant="reverseHolofoil", quantity=1)

    items = store.list_items()
    assert len(items) == 2
    assert {item.variant for item in items} == {"holofoil", "reverseHolofoil"}


def test_remove_decrements_then_deletes_the_row(store):
    store.add("base1-4", variant="holofoil", quantity=3)

    store.remove("base1-4", variant="holofoil", quantity=1)
    assert store.list_items()[0].quantity == 2

    store.remove("base1-4", variant="holofoil", quantity=5)
    assert store.list_items() == []


def test_remove_card_not_in_collection_is_a_no_op(store):
    store.remove("base1-58", variant="normal", quantity=1)

    assert store.list_items() == []


def test_add_unknown_card_raises_value_error(store):
    with pytest.raises(ValueError, match="unknown card"):
        store.add("no-such-card")


def test_total_value_uses_market_price_times_quantity(seeded, store):
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=60.0)

    valuation = store.total_value()

    assert valuation.market_value == 200.0
    assert valuation.cost_basis == 120.0
    assert valuation.unrealized == 80.0
    assert valuation.unpriced_items == 0


def test_item_without_any_snapshot_is_unpriced_but_keeps_cost_basis(store):
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=60.0)

    valuation = store.total_value()

    assert valuation.market_value == 0.0
    assert valuation.cost_basis == 120.0
    assert valuation.unrealized == -120.0
    assert valuation.unpriced_items == 1


def test_cardmarket_aggregate_prices_a_normal_variant_item(seeded, store):
    """Regression guard: cardmarket only ever publishes variant='aggregate', so a
    variant-filtered lookup can never see it and would silently value this card at $0.
    Valuation must delegate to PriceService, which does the explicit fallback."""
    snapshot(seeded, "base1-4", "cardmarket", "aggregate", market=42.0)
    store.add("base1-4", variant="normal", quantity=1)

    valuation = store.total_value()

    assert valuation.market_value == 42.0
    assert valuation.unpriced_items == 0


def test_snapshot_with_null_market_counts_as_unpriced(seeded, store):
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=None)
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=10.0)

    valuation = store.total_value()

    assert valuation.market_value == 0.0
    assert valuation.unpriced_items == 1
    assert valuation.cost_basis == 20.0


def test_portfolio_item_carries_market_price_and_unrealized(seeded, store):
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=60.0)

    item = store.portfolio().items[0]

    assert item.card_name == "Charizard"
    assert item.set_name == "Base"
    assert item.market_price == 100.0
    assert item.market_source == "tcgplayer"
    assert item.unrealized == 80.0  # (100 - 60) * 2
    assert item.priced is True


def test_portfolio_item_unpriced_has_none_market_and_unrealized(store):
    store.add("base1-4", variant="holofoil", quantity=1, acquired_price=60.0)

    item = store.portfolio().items[0]

    assert item.market_price is None
    assert item.market_source is None
    assert item.unrealized is None
    assert item.priced is False


def test_portfolio_item_without_cost_basis_has_none_unrealized(seeded, store):
    """A price with no cost basis is not a gain. unrealized must be None so the UI shows
    an em dash, never market value dressed up as profit."""
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    store.add("base1-4", variant="holofoil", quantity=1)

    item = store.portfolio().items[0]

    assert item.market_price == 100.0
    assert item.unrealized is None


def test_portfolio_summary_totals_and_counts_priced_and_unpriced(seeded, store):
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=60.0)
    store.add("base1-58", variant="normal", quantity=1, acquired_price=5.0)  # unpriced

    summary = store.portfolio().summary

    assert summary.market_value == 200.0
    assert summary.cost_basis == 125.0  # 120 + 5
    assert summary.unrealized == 75.0
    assert summary.priced_items == 1
    assert summary.unpriced_items == 1


def test_summary_allocation_groups_by_set_and_sorts_by_market_value_desc(seeded, store):
    seeded.add(CardSet(id="base2", name="Jungle", series="Base2"))
    seeded.add(Card(id="base2-1", set_id="base2", name="Ivysaur", number="1"))
    seeded.commit()
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    snapshot(seeded, "base2-1", "tcgplayer", "normal", market=10.0)
    store.add("base1-4", variant="holofoil", quantity=1, acquired_price=60.0)
    store.add("base2-1", variant="normal", quantity=1, acquired_price=2.0)

    allocation = store.portfolio().summary.allocation

    assert [a.set_id for a in allocation] == ["base1", "base2"]  # 100 before 10
    assert allocation[0].market_value == 100.0
    assert allocation[0].cost_basis == 60.0
    assert allocation[0].item_count == 1
    assert allocation[1].set_name == "Jungle"


def test_summary_top_movers_exclude_items_missing_price_or_cost_basis(seeded, store):
    """gainers/losers only make sense when both a market price and a cost basis exist;
    an unpriced item or one with no cost basis has no unrealized P/L to rank."""
    snapshot(seeded, "base1-4", "tcgplayer", "holofoil", market=100.0)
    snapshot(seeded, "base1-58", "tcgplayer", "normal", market=50.0)
    store.add("base1-4", variant="holofoil", quantity=1, acquired_price=60.0)  # +40
    store.add("base1-58", variant="normal", quantity=1, acquired_price=80.0)   # -30
    store.add("base1-4", variant="reverseHolofoil", quantity=1, acquired_price=10.0)  # unpriced

    summary = store.portfolio().summary

    mover_ids = {i.card_id for i in summary.top_gainers} | {i.card_id for i in summary.top_losers}
    assert mover_ids == {"base1-4", "base1-58"}  # the reverseHolofoil item is excluded
    assert summary.top_gainers[0].unrealized == 40.0
    assert summary.top_losers[0].unrealized == -30.0


def test_set_cost_basis_updates_acquired_price_acquired_at_and_notes(store):
    store.add("base1-4", variant="holofoil", quantity=1)
    item = store.list_items()[0]
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)

    updated = store.set_cost_basis(item.id, acquired_price=42.0, acquired_at=when, notes="backfill")

    assert updated.acquired_price == 42.0
    assert updated.acquired_at == when
    assert updated.notes == "backfill"
    refreshed = store.list_items()[0]
    assert refreshed.acquired_price == 42.0
    assert refreshed.acquired_at == when


def test_set_cost_basis_unknown_item_id_raises(store):
    with pytest.raises(ValueError, match="unknown item"):
        store.set_cost_basis(999, acquired_price=1.0)


def test_add_now_stamps_acquired_at_on_new_rows(store):
    before = datetime.now(timezone.utc)
    item = store.add("base1-4", variant="holofoil", quantity=1)
    assert item.acquired_at is not None
    assert item.acquired_at.tzinfo is not None
    assert item.acquired_at >= before


def test_add_merge_does_not_overwrite_existing_acquired_at(store):
    """A top-up is not a new purchase: the original acquisition date stays, and the new
    acquired_price is ignored on merge (the per-(card, variant) row keeps its cost basis)."""
    item = store.add("base1-4", variant="holofoil", quantity=1, acquired_price=10.0)
    first_at = item.acquired_at

    store.add("base1-4", variant="holofoil", quantity=1, acquired_price=99.0)

    refreshed = store.list_items()[0]
    assert refreshed.acquired_at == first_at
    assert refreshed.acquired_price == 10.0
