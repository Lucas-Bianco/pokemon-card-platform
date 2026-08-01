from datetime import datetime, timedelta, timezone

import pytest

from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.prices.provider import PriceQuote
from cardplatform.prices.service import PriceService

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def snapshot(
    session,
    card_id="base1-4",
    source="tcgplayer",
    variant="holofoil",
    market=10.0,
    source_updated_at="2026/07/28",
    fetched_at=NOW,
):
    """Insert a PriceSnapshot directly — mirrors the helper in test_api/test_collection.

    fetched_at is controlled explicitly because price_history orders and filters on
    the observation time, not on the free-text source_updated_at stamp.
    """
    session.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            source_updated_at=source_updated_at,
            fetched_at=fetched_at,
        )
    )
    session.commit()


class FakeProvider:
    name = "fake"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch(self, card_id):
        self.calls.append(card_id)
        return self.quotes


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def test_records_snapshot_per_variant(seeded):
    provider = FakeProvider(
        [
            PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
            PriceQuote("base1-4", "tcgplayer", "reverseHolofoil", market=13.41, source_updated_at="2026/07/28"),
        ]
    )

    written = PriceService(seeded, provider).refresh_card("base1-4")

    assert written == 2
    assert seeded.query(PriceSnapshot).count() == 2


def test_same_source_timestamp_is_not_duplicated(seeded):
    quote = PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28")
    service = PriceService(seeded, FakeProvider([quote]))

    service.refresh_card("base1-4")
    second = service.refresh_card("base1-4")

    assert second == 0
    assert seeded.query(PriceSnapshot).count() == 1


def test_quotes_without_timestamp_still_dedupe(seeded):
    """source_updated_at is a non-nullable '' sentinel: NULLs would not collide."""
    quote = PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at=None)
    service = PriceService(seeded, FakeProvider([quote]))

    service.refresh_card("base1-4")
    second = service.refresh_card("base1-4")

    assert second == 0
    assert seeded.query(PriceSnapshot).count() == 1
    assert seeded.query(PriceSnapshot).one().source_updated_at == ""


def test_new_source_timestamp_appends_history(seeded):
    day_one = PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28")
    day_two = PriceQuote("base1-4", "tcgplayer", "holofoil", market=11.02, source_updated_at="2026/07/29")

    PriceService(seeded, FakeProvider([day_one])).refresh_card("base1-4")
    PriceService(seeded, FakeProvider([day_two])).refresh_card("base1-4")

    assert seeded.query(PriceSnapshot).count() == 2


def test_latest_price_prefers_tcgplayer_when_both_sources_have_the_variant(seeded):
    """tcgplayer and cardmarket can both cover a card; tcgplayer must win."""
    quotes = [
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
        PriceQuote("base1-4", "cardmarket", "aggregate", market=2.67, source_updated_at="2026/07/01"),
    ]
    service = PriceService(seeded, FakeProvider(quotes))
    service.refresh_card("base1-4")

    latest = service.latest_price("base1-4", variant="holofoil")

    assert latest.source == "tcgplayer"
    assert latest.market == 9.71


def test_latest_price_falls_back_to_cardmarket_when_no_tcgplayer_row_exists(seeded):
    """Regression guard for the dead-priority-code bug: cardmarket-only cards must
    still price, not silently return None (which would zero them out in valuation)."""
    quote = PriceQuote("base1-4", "cardmarket", "aggregate", market=2.67, source_updated_at="2026/07/01")
    service = PriceService(seeded, FakeProvider([quote]))
    service.refresh_card("base1-4")

    latest = service.latest_price("base1-4", variant="normal")

    assert latest is not None
    assert latest.source == "cardmarket"
    assert latest.market == 2.67


def test_latest_price_returns_newest_of_several_out_of_order_snapshots(seeded):
    """Multiple snapshots for one variant, inserted out of chronological order by
    source_updated_at — latest_price must return the one with the newest fetched_at,
    not rely on insertion order or any incidental row ordering."""
    quotes_in_insertion_order = [
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=5.00, source_updated_at="2026/07/01"),
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=11.02, source_updated_at="2026/07/29"),
    ]
    for quote in quotes_in_insertion_order:
        PriceService(seeded, FakeProvider([quote])).refresh_card("base1-4")

    latest = PriceService(seeded, FakeProvider([])).latest_price("base1-4", variant="holofoil")

    assert latest.market == 11.02
    assert latest.source_updated_at == "2026/07/29"


def test_latest_price_returns_none_when_unpriced(seeded):
    service = PriceService(seeded, FakeProvider([]))
    assert service.latest_price("base1-4", variant="holofoil") is None


def test_refresh_card_without_a_provider_raises(seeded):
    """The provider is optional for read-only consumers, so refresh_card must fail
    loudly rather than dying on an AttributeError against None."""
    service = PriceService(seeded)

    with pytest.raises(RuntimeError, match="without a provider"):
        service.refresh_card("base1-4")


def test_latest_price_works_without_a_provider(seeded):
    """The reason the provider is optional: valuation constructs PriceService(session)
    purely to read prices and never fetches."""
    seeded.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=9.71,
            source_updated_at="2026/07/28",
        )
    )
    seeded.commit()

    latest = PriceService(seeded).latest_price("base1-4", variant="holofoil")

    assert latest is not None
    assert latest.market == 9.71


def test_price_history_returns_snapshots_ordered_oldest_first(seeded):
    snapshot(seeded, market=80.0, source_updated_at="2026/07/01", fetched_at=NOW - timedelta(days=28))
    snapshot(seeded, market=100.0, source_updated_at="2026/07/29", fetched_at=NOW)

    history = PriceService(seeded).price_history("base1-4", "holofoil")

    assert [s.market for s in history] == [80.0, 100.0]
    assert [s.source_updated_at for s in history] == ["2026/07/01", "2026/07/29"]


def test_price_history_prefers_tcgplayer_when_both_sources_share_a_date(seeded):
    """A chart needs one point per date. tcgplayer and cardmarket both covering a date
    must collapse to the tcgplayer point — the same resolution latest_price uses, so the
    chart line and the headline price agree on what 'the price' is."""
    snapshot(seeded, source="tcgplayer", variant="holofoil", market=100.0,
             source_updated_at="2026/07/15", fetched_at=NOW)
    snapshot(seeded, source="cardmarket", variant="aggregate", market=90.0,
             source_updated_at="2026/07/15", fetched_at=NOW)

    history = PriceService(seeded).price_history("base1-4", "holofoil")

    assert len(history) == 1
    assert history[0].source == "tcgplayer"
    assert history[0].market == 100.0


def test_price_history_keeps_cardmarket_only_dates(seeded):
    """tcgplayer-preference must not erase dates only cardmarket covers — those are still
    real observations and the chart would lie about coverage by omitting them."""
    snapshot(seeded, source="cardmarket", variant="aggregate", market=50.0,
             source_updated_at="2026/07/01", fetched_at=NOW - timedelta(days=28))
    snapshot(seeded, source="tcgplayer", variant="holofoil", market=100.0,
             source_updated_at="2026/07/29", fetched_at=NOW)

    history = PriceService(seeded).price_history("base1-4", "holofoil")

    assert [s.source for s in history] == ["cardmarket", "tcgplayer"]
    assert [s.market for s in history] == [50.0, 100.0]


def test_price_history_resolves_normal_variant_via_cardmarket_aggregate(seeded):
    """A normal-variant card priced only by cardmarket (no tcgplayer 'normal' row) must
    still produce history — the aggregate fallback latest_price relies on."""
    snapshot(seeded, source="cardmarket", variant="aggregate", market=50.0,
             source_updated_at="2026/07/01", fetched_at=NOW)

    history = PriceService(seeded).price_history("base1-4", "normal")

    assert len(history) == 1
    assert history[0].source == "cardmarket"
    assert history[0].market == 50.0


def test_price_history_excludes_other_variants(seeded):
    """Asking for holofoil history must not pull in reverseHolofoil snapshots — a variant
    series mixed with another variant's prices is not a series of one price."""
    snapshot(seeded, source="tcgplayer", variant="holofoil", market=100.0,
             source_updated_at="2026/07/29", fetched_at=NOW)
    snapshot(seeded, source="tcgplayer", variant="reverseHolofoil", market=20.0,
             source_updated_at="2026/07/29", fetched_at=NOW)

    history = PriceService(seeded).price_history("base1-4", "holofoil")

    assert len(history) == 1
    assert history[0].market == 100.0


def test_price_history_since_filter_excludes_older(seeded):
    snapshot(seeded, market=80.0, source_updated_at="2026/07/01", fetched_at=NOW - timedelta(days=28))
    snapshot(seeded, market=100.0, source_updated_at="2026/07/29", fetched_at=NOW)

    cutoff = NOW - timedelta(days=14)
    history = PriceService(seeded).price_history("base1-4", "holofoil", since=cutoff)

    assert [s.market for s in history] == [100.0]


def test_price_history_days_filter_excludes_older_than_days(seeded, monkeypatch):
    """days is a convenience over since = now - days. Pin 'now' so the window is
    deterministic regardless of when the suite runs."""
    from cardplatform.prices import service as service_module

    snapshot(seeded, market=80.0, source_updated_at="2026/07/01", fetched_at=NOW - timedelta(days=30))
    snapshot(seeded, market=100.0, source_updated_at="2026/07/29", fetched_at=NOW)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return NOW

    monkeypatch.setattr(service_module, "datetime", FakeDateTime)

    history = PriceService(seeded).price_history("base1-4", "holofoil", days=14)

    assert [s.market for s in history] == [100.0]


def test_price_history_empty_when_no_snapshots(seeded):
    assert PriceService(seeded).price_history("base1-4", "holofoil") == []
