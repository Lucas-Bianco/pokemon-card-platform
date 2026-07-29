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
