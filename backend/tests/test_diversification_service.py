"""Row 23: CollectionStore.diversification() — concentration + diversification of
the collection's *priced* value.

priced_total is the sum of market x quantity across priced holdings only.
Shares are computed against priced_total; unpriced cards are counted in
unpriced_items and excluded from every total and every share, never estimated
at $0. Concentration ratios (cards_for_50/80/90) are None when there is no
priced value. Buckets by rarity / supertype / set group every holding — an
all-unpriced bucket still appears at share 0.0.
"""
from __future__ import annotations

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, PriceSnapshot


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
    db.add(
        Card(
            id="base2-1", set_id="base2", name="Energy", number="1",
            rarity="Common", supertype="Energy",
        )
    )
    db.commit()
    return db


@pytest.fixture
def store(seeded):
    return CollectionStore(seeded)


def snap(session, card_id, source, variant, market, source_updated_at="2026/07/28"):
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


def test_empty_collection_has_no_priced_value_and_no_concentration(store):
    d = store.diversification()
    assert d.priced_total == 0.0
    assert d.priced_items == 0
    assert d.unpriced_items == 0
    assert d.total_items == 0
    assert d.top_holdings == []
    assert d.concentration.top_share is None
    assert d.concentration.cards_for_50 is None
    assert d.concentration.cards_for_80 is None
    assert d.concentration.cards_for_90 is None
    assert d.concentration.priced_holdings == 0
    assert d.by_rarity == []
    assert d.by_supertype == []
    assert d.by_set == []
    assert d.caveat  # never empty


def test_all_unpriced_collection_excludes_value_never_zero(store, seeded):
    # base1-4 has a snapshot with market=None; base1-58 has no snapshot at all.
    snap(seeded, "base1-4", "tcgplayer", "normal", market=None)
    store.add("base1-4", quantity=2)
    store.add("base1-58", quantity=1)

    d = store.diversification()
    assert d.priced_total == 0.0  # never fabricated
    assert d.priced_items == 0
    assert d.unpriced_items == 2
    assert d.total_items == 2
    assert d.top_holdings == []
    assert d.concentration.top_share is None
    # Buckets still list the all-unpriced groupings, each at share 0.0.
    by_rarity = {b.label: b for b in d.by_rarity}
    assert by_rarity["Rare Holo"].market_value == 0.0
    assert by_rarity["Rare Holo"].share == 0.0
    assert by_rarity["Rare Holo"].holdings == 1
    assert by_rarity["Common"].holdings == 1


def test_priced_holding_ranked_with_share_and_cumulative(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0)
    store.add("base1-4", quantity=2)  # market value 200

    d = store.diversification()
    assert d.priced_total == 200.0
    assert d.priced_items == 1
    assert d.unpriced_items == 0
    top = d.top_holdings[0]
    assert top.card_id == "base1-4"
    assert top.card_name == "Charizard"
    assert top.set_name == "Base"
    assert top.variant == "normal"
    assert top.quantity == 2
    assert top.market_value == 200.0
    assert top.share == 1.0
    assert top.cumulative_share == 1.0


def test_concentration_ratios_count_holdings_to_threshold(store, seeded):
    # 70 / 20 / 10 split -> priced_total 100.
    snap(seeded, "base1-4", "tcgplayer", "normal", market=70.0)
    snap(seeded, "base1-58", "tcgplayer", "normal", market=20.0)
    snap(seeded, "base2-1", "tcgplayer", "normal", market=10.0)
    store.add("base1-4", quantity=1)
    store.add("base1-58", quantity=1)
    store.add("base2-1", quantity=1)

    d = store.diversification()
    assert d.priced_total == 100.0
    c = d.concentration
    assert c.top_share == pytest.approx(0.7)
    assert c.cards_for_50 == 1   # top card alone is 70%
    assert c.cards_for_80 == 2   # 70+20 = 90 >= 80
    assert c.cards_for_90 == 2   # 90 >= 90
    assert c.priced_holdings == 3
    # Cumulative share on the top list reaches 1.0 by the last ranked holding.
    assert d.top_holdings[-1].cumulative_share == pytest.approx(1.0)


def test_top_holdings_capped_at_ten_and_sorted_desc(store, seeded):
    # 12 distinct priced holdings, values 12..1 — only the 10 largest appear,
    # in descending order, and the smallest two are dropped from the top list.
    db = seeded
    for i in range(12):
        db.add(
            Card(
                id=f"base1-x{i}", set_id="base1", name=f"Slot{i}", number=str(i),
                rarity="Common", supertype="Pokemon",
            )
        )
        snap(seeded, f"base1-x{i}", "tcgplayer", "normal", market=float(12 - i))
        store.add(f"base1-x{i}", quantity=1)
    db.commit()

    d = store.diversification()
    assert len(d.top_holdings) == 10
    # Descending by market value.
    values = [h.market_value for h in d.top_holdings]
    assert values == sorted(values, reverse=True)
    assert values[0] == 12.0
    assert values[-1] == 3.0  # 12..1, the 10 largest are 12..3


def test_unpriced_holding_excluded_from_shares_but_counted(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0)  # priced
    store.add("base1-4", quantity=1)
    store.add("base1-58", quantity=5)  # unpriced, no snapshot
    store.add("base2-1", quantity=1)   # unpriced, no snapshot

    d = store.diversification()
    assert d.priced_total == 100.0
    assert d.priced_items == 1
    assert d.unpriced_items == 2
    assert d.total_items == 3
    # The priced holding is 100% of priced value, not diluted by the unpriced.
    assert d.top_holdings[0].share == pytest.approx(1.0)
    # The unpriced holdings still appear in buckets, contributing 0 to value.
    by_set = {b.label: b for b in d.by_set}
    assert by_set["Base"].market_value == 100.0
    assert by_set["Base"].holdings == 2  # priced Charizard + unpriced Pikachu
    assert by_set["Jungle"].market_value == 0.0
    assert by_set["Jungle"].holdings == 1


def test_by_rarity_and_supertype_buckets_share_against_priced_total(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=100.0)  # Rare Holo / Pokemon
    snap(seeded, "base2-1", "tcgplayer", "normal", market=50.0)   # Common / Energy
    store.add("base1-4", quantity=1)
    store.add("base2-1", quantity=1)

    d = store.diversification()
    assert d.priced_total == 150.0
    by_rarity = {b.label: b for b in d.by_rarity}
    assert by_rarity["Rare Holo"].market_value == 100.0
    assert by_rarity["Rare Holo"].share == pytest.approx(100.0 / 150.0)
    assert by_rarity["Common"].market_value == 50.0
    assert by_rarity["Common"].share == pytest.approx(50.0 / 150.0)
    by_super = {b.label: b for b in d.by_supertype}
    assert by_super["Pokemon"].market_value == 100.0
    assert by_super["Energy"].market_value == 50.0
    # Buckets are sorted by market value desc.
    assert d.by_rarity[0].label == "Rare Holo"


def test_unknown_label_when_rarity_or_supertype_missing(store, seeded):
    # A card with null rarity/supertype groups under "Unknown", never dropped.
    db = seeded
    db.add(
        Card(
            id="base1-99", set_id="base1", name="Mystery", number="99",
            rarity=None, supertype=None,
        )
    )
    db.commit()
    snap(seeded, "base1-99", "tcgplayer", "normal", market=30.0)
    store.add("base1-99", quantity=1)

    d = store.diversification()
    assert d.priced_total == 30.0
    assert d.by_rarity[0].label == "Unknown"
    assert d.by_rarity[0].share == pytest.approx(1.0)
    assert d.by_supertype[0].label == "Unknown"


def test_cardmarket_fallback_snapshot_used_for_pricing(store, seeded):
    # latest_price prefers tcgplayer then cardmarket/aggregate; a cardmarket-only
    # snapshot still prices the holding and flows into priced_total.
    snap(seeded, "base1-4", "cardmarket", "aggregate", market=80.0)
    store.add("base1-4", quantity=2)
    d = store.diversification()
    assert d.priced_total == 160.0
    assert d.top_holdings[0].market_value == 160.0


def test_variant_specific_snapshot_used(store, seeded):
    snap(seeded, "base1-4", "tcgplayer", "holofoil", market=200.0)
    store.add("base1-4", variant="holofoil", quantity=1)
    store.add("base1-4", variant="normal", quantity=1)  # no normal snapshot -> unpriced
    d = store.diversification()
    assert d.priced_total == 200.0
    assert d.priced_items == 1
    assert d.unpriced_items == 1
    assert d.top_holdings[0].variant == "holofoil"


def test_concentration_thresholds_reachable_at_full_collection(store, seeded):
    # Four equal holdings of 25% each: 50% at 2, 75% at 3 (under 80), 100% at 4
    # (>= 80 and >= 90). The full priced collection always sums to 100%, so the
    # 80/90 thresholds are reachable at the last holding, not left None.
    snap(seeded, "base1-4", "tcgplayer", "normal", market=25.0)
    snap(seeded, "base1-58", "tcgplayer", "normal", market=25.0)
    snap(seeded, "base2-1", "tcgplayer", "normal", market=25.0)
    db = seeded
    db.add(Card(id="base1-7", set_id="base1", name="Clefairy", number="7",
                rarity="Common", supertype="Pokemon"))
    db.commit()
    snap(seeded, "base1-7", "tcgplayer", "normal", market=25.0)
    store.add("base1-4", quantity=1)
    store.add("base1-58", quantity=1)
    store.add("base2-1", quantity=1)
    store.add("base1-7", quantity=1)

    d = store.diversification()
    c = d.concentration
    assert c.cards_for_50 == 2   # 25+25 = 50
    assert c.cards_for_80 == 4  # 75% at 3 is under 80; 100% at 4 reaches it
    assert c.cards_for_90 == 4  # 100% at 4 reaches 90 too
    assert c.priced_holdings == 4