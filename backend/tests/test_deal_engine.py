"""T2: DealEngine — read-only rip-vs-flip evaluation of active listings (Phase 05).

Mirrors test_price_service.py / test_listings_service.py: a seeded card+set FK
fixture and direct snapshot inserts. DealEngine writes nothing; deals are
derived from the newest snapshots each call. Missing inputs null the edge
they feed — never a fabricated $0, never a fake profit.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.db.models import Card, CardSet, GradedPriceSnapshot, ListingSnapshot, PriceSnapshot
from cardplatform.deals.engine import DealEngine


def _add_price(session, card_id, variant, market, source="tcgplayer", stamp="2026-08-01"):
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            source_updated_at=stamp,
        )
    )
    session.commit()


def _add_graded(session, card_id, variant, grade, market, grader="PSA", stamp="2026-08-01"):
    session.add(
        GradedPriceSnapshot(
            card_id=card_id,
            grader=grader,
            grade=grade,
            variant=variant,
            market=market,
            source="pkmnprices",
            source_updated_at=stamp,
        )
    )
    session.commit()


def _add_listing(
    session,
    card_id,
    variant,
    listing_id,
    price,
    listing_type="fixed_price",
    auction_end_at=None,
    fetched_at=None,
):
    session.add(
        ListingSnapshot(
            card_id=card_id,
            variant=variant,
            source="ebay",
            listing_id=listing_id,
            title="t",
            price=price,
            currency="USD",
            listing_type=listing_type,
            auction_end_at=auction_end_at,
            url="u",
            condition="Raw",
            source_updated_at="",
            fetched_at=fetched_at or datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    session.commit()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def test_rip_edge_below_market_is_flagged(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    _add_listing(seeded, "base1-4", "holofoil", "L1", 100.0)  # 20 below market
    engine = DealEngine(seeded, database.settings)
    deals = engine.assess("base1-4", "holofoil")
    assert len(deals) == 1
    d = deals[0]
    assert d.rip_edge == 20.0
    assert d.is_rip is True  # 20 >= 2.0 and 20 >= 0.10*120=12
    assert d.raw_market.price == 120.0


def test_small_rip_below_threshold_not_flagged(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    _add_listing(seeded, "base1-4", "holofoil", "L1", 117.0)  # 3 below, 2.5% — under pct threshold
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.rip_edge == 3.0
    assert d.is_rip is False  # 3 < 12 (10% of 120)


def test_flip_edge_to_10_with_grading_fee(seeded, database):
    # fee 25; listing 100; psa10 200 -> flip_to_10 = 200-100-25 = 75
    _add_graded(seeded, "base1-4", "holofoil", 10, 200.0)
    _add_graded(seeded, "base1-4", "holofoil", 9, 150.0)
    _add_listing(seeded, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.flip_edge_to_10 == 75.0
    assert d.flip_edge_to_9 == 25.0
    assert d.is_flip is True  # 75 >= 20


def test_no_raw_market_nulls_rip_edge(seeded, database):
    _add_listing(seeded, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.rip_edge is None
    assert d.raw_market is None
    assert d.is_rip is False


def test_no_graded_comps_nulls_flip_edges(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    _add_listing(seeded, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.flip_edge_to_9 is None
    assert d.flip_edge_to_10 is None
    assert d.psa9_comp is None and d.psa10_comp is None
    assert d.is_flip is False


def test_no_listings_returns_empty(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    engine = DealEngine(seeded, database.settings)
    assert engine.assess("base1-4", "holofoil") == []


def test_deals_ranked_by_score_desc_nulls_last(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    _add_graded(seeded, "base1-4", "holofoil", 10, 200.0)
    _add_listing(seeded, "base1-4", "holofoil", "big", 80.0)  # rip 40, flip 95 -> score 95
    _add_listing(seeded, "base1-4", "holofoil", "small", 115.0)  # rip 5  -> score 5
    engine = DealEngine(seeded, database.settings)
    deals = engine.assess("base1-4", "holofoil")
    assert [d.listing_id for d in deals] == ["big", "small"]


def test_unpriced_listing_kept_with_null_edges(seeded, database):
    _add_price(seeded, "base1-4", "holofoil", 120.0)
    _add_listing(seeded, "base1-4", "holofoil", "L1", None)  # price None
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.listing_price is None
    assert d.rip_edge is None and d.flip_edge_to_10 is None


def test_thresholds_field_in_assessment(seeded, database):
    _add_listing(seeded, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(seeded, database.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.thresholds.deal_rip_min_abs == database.settings.deal_rip_min_abs