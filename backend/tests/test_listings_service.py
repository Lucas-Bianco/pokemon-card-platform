"""T2: ListingsService — immutable persistence, dedupe, latest-listing resolution.

Mirrors test_graded_price_service.py: a FakeProvider, a card+set FK fixture,
and direct snapshot inserts to control fetched_at ordering. Snapshots are
immutable and deduped on (card_id, variant, source, listing_id,
source_updated_at); the empty-string sentinel makes a missing stamp collide
correctly under the unique constraint instead of silently duplicating.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cardplatform.db.models import Card, CardSet, ListingSnapshot
from cardplatform.prices.listings_provider import ListingQuote
from cardplatform.prices.listings_service import ListingsService


class FakeListingsProvider:
    name = "fake"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch_listings(self, card_id, variant):
        self.calls.append((card_id, variant))
        return self.quotes


def _quote(
    card_id="base1-4",
    variant="normal",
    listing_id="ebay-1",
    price=25.0,
    source="ebay",
    source_updated_at=None,
    listing_type="fixed_price",
):
    return ListingQuote(
        card_id=card_id,
        variant=variant,
        listing_id=listing_id,
        title="Charizard",
        price=price,
        currency="USD",
        listing_type=listing_type,
        auction_end_at=None,
        url="https://www.ebay.com/itm/1",
        condition="Used",
        source=source,
        source_updated_at=source_updated_at,
    )


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def test_refresh_dedupes_and_is_immutable(seeded):
    """Provider returns 2 identical quotes across two refresh calls: first writes 2,
    second writes 0; DB has 2 rows. Re-fetching the same listing_id with the same
    source_updated_at is dropped by dedupe — snapshots are immutable, never
    overwritten in place."""
    quotes = [
        _quote(listing_id="ebay-A", price=10.0),
        _quote(listing_id="ebay-B", price=20.0),
    ]
    service = ListingsService(seeded, FakeListingsProvider(quotes))

    first = service.refresh_listings("base1-4", "normal")
    second = service.refresh_listings("base1-4", "normal")

    assert first == 2
    assert second == 0
    assert seeded.query(ListingSnapshot).count() == 2

    # Re-fetch with a DIFFERENT price but the same unique key — immutable, dropped.
    service3 = ListingsService(
        seeded,
        FakeListingsProvider(
            [
                _quote(listing_id="ebay-A", price=999.0),
                _quote(listing_id="ebay-B", price=888.0),
            ]
        ),
    )
    third = service3.refresh_listings("base1-4", "normal")
    assert third == 0
    rows = seeded.query(ListingSnapshot).order_by(ListingSnapshot.id).all()
    assert len(rows) == 2
    assert {r.price for r in rows} == {10.0, 20.0}  # originals preserved


def test_latest_listings_newest_first_lowest_price_first(seeded):
    """Old snapshot (t1) with 1 listing price 50, then new snapshot (t2 > t1) with
    listings price 30 + price 10 → latest_listings returns the t2 rows ordered
    price asc (10 then 30). Control fetched_at via direct inserts."""
    t1 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=1)

    # Old snapshot
    seeded.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="normal",
            source="ebay",
            listing_id="old-1",
            price=50.0,
            currency="USD",
            source_updated_at="",
            fetched_at=t1,
        )
    )
    # New snapshot — two listings
    seeded.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="normal",
            source="ebay",
            listing_id="new-1",
            price=30.0,
            currency="USD",
            source_updated_at="",
            fetched_at=t2,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4",
            variant="normal",
            source="ebay",
            listing_id="new-2",
            price=10.0,
            currency="USD",
            source_updated_at="",
            fetched_at=t2,
        )
    )
    seeded.commit()

    latest = ListingsService(seeded).latest_listings("base1-4", "normal")

    assert len(latest) == 2
    assert latest[0].price == 10.0
    assert latest[1].price == 30.0
    # The t1 listing is NOT in latest (which is only the newest fetched_at)
    assert {row.listing_id for row in latest} == {"new-1", "new-2"}


def test_has_stock_and_lowest_price(seeded):
    """Provider returns [] → has_stock=False, lowest_price=None (NOT 0.0). Then one
    listing price 25 → has_stock=True, lowest_price==25.0."""
    service = ListingsService(seeded, FakeListingsProvider([]))

    assert service.has_stock("base1-4", "normal") is False
    assert service.lowest_price("base1-4", "normal") is None
    assert service.lowest_price("base1-4", "normal") != 0.0

    service2 = ListingsService(seeded, FakeListingsProvider([_quote(price=25.0)]))
    service2.refresh_listings("base1-4", "normal")

    assert service2.has_stock("base1-4", "normal") is True
    assert service2.lowest_price("base1-4", "normal") == 25.0


def test_previous_listing_ids(seeded):
    """First refresh lists {A,B} at t1, second refresh lists {B,C} at t2 →
    previous_listing_ids() returns {A,B} (the prior snapshot's ids). Before the
    second refresh, previous_listing_ids returns set()."""
    # First refresh — control fetched_at so we get two distinct fetches.
    t1 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="A",
            price=10.0, currency="USD", source_updated_at="", fetched_at=t1,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="B",
            price=20.0, currency="USD", source_updated_at="", fetched_at=t1,
        )
    )
    seeded.commit()

    service = ListingsService(seeded)
    # Only one fetch so far → no prior snapshot
    assert service.previous_listing_ids("base1-4", "normal") == set()

    # Second fetch at t2
    t2 = t1 + timedelta(hours=1)
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="B",
            price=22.0, currency="USD", source_updated_at="v2", fetched_at=t2,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="C",
            price=30.0, currency="USD", source_updated_at="v2", fetched_at=t2,
        )
    )
    seeded.commit()

    assert service.previous_listing_ids("base1-4", "normal") == {"A", "B"}


def test_refresh_no_provider_raises(seeded):
    """ListingsService(session) with provider=None → refresh_listings raises
    RuntimeError, not AttributeError."""
    service = ListingsService(seeded)

    with pytest.raises(RuntimeError, match="without a provider"):
        service.refresh_listings("base1-4", "normal")


def test_refresh_no_key_returns_zero(seeded):
    """A provider with no key returns [] — the service just sees [] and returns 0,
    no raise (the provider itself never raises)."""
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.config import Settings

    provider = EbayListingsProvider(Settings(listings_api_key=None))
    service = ListingsService(seeded, provider)

    written = service.refresh_listings("base1-4", "normal")

    assert written == 0
    assert seeded.query(ListingSnapshot).count() == 0


def test_previous_listing_ids_tie_merges_same_timestamp_fetches(seeded):
    """Two real fetches share the SAME fetched_at (Windows ~15ms clock tie
    between a baseline refresh and an immediate poll). Without a per-fetch id
    column, the two commits are data-indistinguishable from one merged
    multi-row fetch — so `previous_listing_ids` treats them as a single
    "latest" snapshot and returns set() (no prior distinct fetched_at). This
    documents the known limitation: T3 must ensure baseline and first poll land
    in distinct clock ticks (e.g. stamp fetched_at per-call) if strict
    tied-fetch separation is required. A future fetch_id column would let us
    split them; for now this is the honest empty state, NOT a fabricated prior.

    This test locks in the fetched_at-grouping discipline: the `id.desc()`
    tiebreak on the latest-row resolution is honored but does not split a
    shared fetched_at into two fetch groups.
    """
    t = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    # "Baseline" fetch — two rows committed first (lower ids).
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="A",
            price=10.0, currency="USD", source_updated_at="", fetched_at=t,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="B",
            price=20.0, currency="USD", source_updated_at="", fetched_at=t,
        )
    )
    # "Poll" fetch — one row committed second (higher id), SAME fetched_at.
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="C",
            price=30.0, currency="USD", source_updated_at="v2", fetched_at=t,
        )
    )
    seeded.commit()

    prior = ListingsService(seeded).previous_listing_ids("base1-4", "normal")

    # Shared fetched_at → one merged "latest" fetch → no prior fetch → set().
    # (NOT {A,B}: that would require splitting a shared-timestamp fetch, which
    # needs a per-fetch id column we don't have in T2's schema.)
    assert prior == set()

    # And latest_listings returns all three merged rows (the latest fetch).
    latest = ListingsService(seeded).latest_listings("base1-4", "normal")
    assert {r.listing_id for r in latest} == {"A", "B", "C"}

    # With a genuinely older fetch present, the prior is the older fetch.
    t_old = t - timedelta(hours=1)
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="D",
            price=5.0, currency="USD", source_updated_at="", fetched_at=t_old,
        )
    )
    seeded.commit()
    prior2 = ListingsService(seeded).previous_listing_ids("base1-4", "normal")
    assert prior2 == {"D"}


def test_latest_listings_orders_null_price_last(seeded):
    """In the newest snapshot, a priced row must sort BEFORE a None-price row
    (NULLS LAST) so the UI shows priced listings first. Locks in the
    `price.is_(None)` ordering branch."""
    t = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="priced",
            price=30.0, currency="USD", source_updated_at="", fetched_at=t,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="unpriced",
            price=None, currency=None, source_updated_at="", fetched_at=t,
        )
    )
    seeded.add(
        ListingSnapshot(
            card_id="base1-4", variant="normal", source="ebay", listing_id="cheap",
            price=10.0, currency="USD", source_updated_at="", fetched_at=t,
        )
    )
    seeded.commit()

    rows = ListingsService(seeded).latest_listings("base1-4", "normal")

    assert [r.listing_id for r in rows] == ["cheap", "priced", "unpriced"]