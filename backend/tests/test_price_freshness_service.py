"""Row 26: CollectionStore.price_freshness() — band the collection's priced
holdings by the age of their latest price snapshot's fetched_at (when the app last
refreshed each holding's price). Staleness is by our refresh time, not the
provider's data stamp. Unpriced holdings are counted separately and excluded from
every band, never $0. Bands are always the four labels in order, even when empty.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


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


def hold(session, card_id, variant="normal", quantity=1):
    session.add(
        CollectionItem(
            card_id=card_id, variant=variant, quantity=quantity,
            acquired_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()


def snap(session, card_id, source, variant, market, fetched_at, source_updated_at=None):
    if source_updated_at is None:
        source_updated_at = fetched_at.strftime("%Y/%m/%d")
    session.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant, market=market,
            fetched_at=fetched_at, source_updated_at=source_updated_at,
        )
    )
    session.commit()


def days_ago(n):
    return NOW - timedelta(days=n)


def labels(freshness):
    return [b.label for b in freshness.bands]


def band(freshness, label):
    return next(b for b in freshness.bands if b.label == label)


def test_empty_collection_returns_four_zero_bands(store):
    f = store.price_freshness(now=NOW)
    assert labels(f) == ["fresh", "aging", "stale", "outdated"]
    for b in f.bands:
        assert b.holdings == 0
        assert b.market_value == 0.0
        assert b.share == 0.0
    assert f.priced_holdings == 0
    assert f.unpriced_holdings == 0
    assert f.total_holdings == 0
    assert f.oldest_fetched_at is None
    assert f.newest_fetched_at is None
    assert f.caveat


def test_holdings_with_no_snapshots_all_unpriced_never_zero(store, seeded):
    hold(seeded, "base1-4")
    hold(seeded, "base1-58")
    f = store.price_freshness(now=NOW)
    assert f.priced_holdings == 0
    assert f.unpriced_holdings == 2
    assert f.total_holdings == 2
    for b in f.bands:
        assert b.holdings == 0
        assert b.market_value == 0.0  # never $0 — unpriced is a count, not a value


def test_fresh_holding_lands_in_fresh_band_with_full_share(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").holdings == 1
    assert band(f, "fresh").market_value == 10.0
    assert band(f, "fresh").share == 1.0
    assert f.priced_holdings == 1
    assert f.unpriced_holdings == 0


def test_each_age_band_gets_the_right_holding(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    hold(seeded, "base1-58", quantity=1)
    # one snapshot per card at different ages
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))    # fresh
    # Pikachu needs its own snapshot; use a second card variant to avoid the
    # unique constraint, then a third holding for outdated.
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").holdings == 1


def test_all_four_bands_populated_at_boundaries(store, seeded):
    # One holding per band, at the band's start age (fresh=3d, aging=10d,
    # stale=45d, outdated=100d). Uses two cards x two variants to keep snapshots
    # unique on (card_id, source, variant, source_updated_at).
    hold(seeded, "base1-4", variant="normal", quantity=1)
    hold(seeded, "base1-4", variant="holofoil", quantity=1)
    hold(seeded, "base1-58", variant="normal", quantity=1)
    hold(seeded, "base1-58", variant="holofoil", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))      # fresh
    snap(seeded, "base1-4", "tcgplayer", "holofoil", 20.0, days_ago(10))   # aging
    snap(seeded, "base1-58", "tcgplayer", "normal", 30.0, days_ago(45))    # stale
    snap(seeded, "base1-58", "tcgplayer", "holofoil", 40.0, days_ago(100)) # outdated
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").holdings == 1
    assert band(f, "aging").holdings == 1
    assert band(f, "stale").holdings == 1
    assert band(f, "outdated").holdings == 1
    assert f.priced_holdings == 4
    total = 10.0 + 20.0 + 30.0 + 40.0
    assert f.priced_value_total == total
    # shares sum to 1.0 across the four bands.
    assert round(sum(b.share for b in f.bands), 9) == 1.0


def test_band_boundaries_are_exclusive_on_upper_bound(store, seeded):
    # age exactly 7 -> aging (>=7, since fresh is <7). 30 -> stale. 90 -> outdated.
    hold(seeded, "base1-4", variant="normal", quantity=1)
    hold(seeded, "base1-4", variant="holofoil", quantity=1)
    hold(seeded, "base1-58", variant="normal", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(7))    # aging
    snap(seeded, "base1-4", "tcgplayer", "holofoil", 20.0, days_ago(30))  # stale
    snap(seeded, "base1-58", "tcgplayer", "normal", 30.0, days_ago(90))  # outdated
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").holdings == 0
    assert band(f, "aging").holdings == 1
    assert band(f, "stale").holdings == 1
    assert band(f, "outdated").holdings == 1


def test_multiple_holdings_in_a_band_are_summed(store, seeded):
    hold(seeded, "base1-4", variant="normal", quantity=2)
    hold(seeded, "base1-58", variant="normal", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(2))  # 10 x 2 = 20
    snap(seeded, "base1-58", "tcgplayer", "normal", 15.0, days_ago(4))  # 15 x 1 = 15
    f = store.price_freshness(now=NOW)
    fresh = band(f, "fresh")
    assert fresh.holdings == 2
    assert fresh.quantity == 3
    assert fresh.market_value == 35.0
    assert fresh.share == 1.0


def test_unpriced_holding_excluded_from_bands_and_value(store, seeded):
    hold(seeded, "base1-4", quantity=1)   # priced, fresh
    hold(seeded, "base1-58", quantity=1)  # never priced
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").holdings == 1
    assert band(f, "fresh").market_value == 10.0
    assert f.priced_holdings == 1
    assert f.unpriced_holdings == 1
    assert f.priced_value_total == 10.0


def test_snapshot_with_null_market_counts_as_unpriced(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    # A snapshot exists but carries no market figure — the holding is unpriced,
    # never dropped silently nor valued at $0.
    snap(seeded, "base1-4", "tcgplayer", "normal", None, days_ago(3))
    f = store.price_freshness(now=NOW)
    assert f.priced_holdings == 0
    assert f.unpriced_holdings == 1
    for b in f.bands:
        assert b.holdings == 0


def test_quantity_multiplies_band_market_value(store, seeded):
    hold(seeded, "base1-4", quantity=3)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(2))
    f = store.price_freshness(now=NOW)
    assert band(f, "fresh").market_value == 30.0
    assert band(f, "fresh").quantity == 3


def test_oldest_and_newest_fetched_at_span_priced_holdings(store, seeded):
    hold(seeded, "base1-4", variant="normal", quantity=1)
    hold(seeded, "base1-4", variant="holofoil", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(100))
    snap(seeded, "base1-4", "tcgplayer", "holofoil", 20.0, days_ago(2))
    f = store.price_freshness(now=NOW)
    assert f.oldest_fetched_at == days_ago(100)
    assert f.newest_fetched_at == days_ago(2)


def test_cardmarket_fallback_prices_a_holding_and_uses_its_fetched_at(store, seeded):
    # No TCGplayer snapshot — latest_price falls back to the Cardmarket aggregate,
    # so the holding IS priced and its fetched_at seeds the band age.
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "cardmarket", "aggregate", 18.0, days_ago(40))
    f = store.price_freshness(now=NOW)
    assert f.priced_holdings == 1
    assert band(f, "stale").holdings == 1
    assert band(f, "stale").market_value == 18.0


def test_bands_always_four_in_order_even_when_some_empty(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))  # only fresh
    f = store.price_freshness(now=NOW)
    assert labels(f) == ["fresh", "aging", "stale", "outdated"]
    assert band(f, "fresh").holdings == 1
    assert band(f, "aging").holdings == 0
    assert band(f, "stale").holdings == 0
    assert band(f, "outdated").holdings == 0
    assert [b.max_age_days for b in f.bands] == [7, 30, 90, None]


def test_caveat_is_honest_about_refresh_and_never_zero(store):
    f = store.price_freshness(now=NOW)
    assert "refresh" in f.caveat.lower()
    assert "$0" in f.caveat or "never $0" in f.caveat.lower()


def test_now_defaults_to_real_time_without_crashing(store, seeded):
    hold(seeded, "base1-4", quantity=1)
    snap(seeded, "base1-4", "tcgplayer", "normal", 10.0, days_ago(3))
    f = store.price_freshness()  # no pinned now
    assert f.priced_holdings == 1
    # The 3-day-old snapshot is fresh against the real clock too.
    assert band(f, "fresh").holdings == 1