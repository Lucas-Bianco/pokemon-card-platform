"""T4: GradedPriceService — immutable persistence, dedupe, latest_graded resolution.

Mirrors test_price_service.py: a FakeProvider, a card+set FK fixture, and
direct snapshot inserts to control fetched_at ordering. Snapshots are immutable
and deduped on (card_id, grader, grade, variant, source_updated_at); the
empty-string sentinel makes a missing stamp collide correctly under the
unique constraint instead of silently duplicating.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cardplatform.db.models import Card, CardSet, GradedPriceSnapshot
from cardplatform.prices.graded_provider import GradedPriceQuote
from cardplatform.prices.graded_service import GradedPriceService

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class FakeGradedProvider:
    name = "fake"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch_graded(self, card_id):
        self.calls.append(card_id)
        return self.quotes


def _quote(
    card_id="base1-4",
    grader="PSA",
    grade=10.0,
    variant="aggregate",
    market=275.0,
    source="pkmnprices",
    source_updated_at="2025-01-20",
):
    return GradedPriceQuote(
        card_id=card_id,
        grader=grader,
        grade=grade,
        variant=variant,
        low=market,
        mid=market,
        high=market,
        market=market,
        source=source,
        source_updated_at=source_updated_at,
    )


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def test_records_snapshot_per_grader_grade_bucket(seeded):
    provider = FakeGradedProvider(
        [
            _quote(grade=10.0, market=275.0, source_updated_at="2025-01-20"),
            _quote(grade=9.0, market=120.0, source_updated_at="2025-01-18"),
            _quote(grader="CGC", grade=9.5, market=150.0, source_updated_at="2025-01-16"),
        ]
    )

    written = GradedPriceService(seeded, provider).refresh_graded("base1-4")

    assert written == 3
    assert seeded.query(GradedPriceSnapshot).count() == 3


def test_same_source_timestamp_is_not_duplicated(seeded):
    quote = _quote(source_updated_at="2025-01-20")
    service = GradedPriceService(seeded, FakeGradedProvider([quote]))

    service.refresh_graded("base1-4")
    second = service.refresh_graded("base1-4")

    assert second == 0
    assert seeded.query(GradedPriceSnapshot).count() == 1


def test_quotes_without_timestamp_still_dedupe(seeded):
    """source_updated_at None -> '' sentinel: NULLs would not collide under the
    unique constraint, so the service normalizes None to '' (mirrors PriceSnapshot)."""
    quote = _quote(source_updated_at=None)
    service = GradedPriceService(seeded, FakeGradedProvider([quote]))

    service.refresh_graded("base1-4")
    second = service.refresh_graded("base1-4")

    assert second == 0
    assert seeded.query(GradedPriceSnapshot).count() == 1
    assert seeded.query(GradedPriceSnapshot).one().source_updated_at == ""


def test_new_source_timestamp_appends_history(seeded):
    day_one = _quote(market=275.0, source_updated_at="2025-01-20")
    day_two = _quote(market=320.0, source_updated_at="2025-02-01")

    GradedPriceService(seeded, FakeGradedProvider([day_one])).refresh_graded("base1-4")
    GradedPriceService(seeded, FakeGradedProvider([day_two])).refresh_graded("base1-4")

    assert seeded.query(GradedPriceSnapshot).count() == 2


def test_refresh_graded_returns_zero_when_provider_returns_empty(seeded):
    """[] is the honest 'graded prices unavailable' state (no key / 404 / transport
    failure) — it is NOT an error, and must not raise."""
    service = GradedPriceService(seeded, FakeGradedProvider([]))

    written = service.refresh_graded("base1-4")

    assert written == 0
    assert seeded.query(GradedPriceSnapshot).count() == 0


def test_refresh_graded_without_provider_raises(seeded):
    """The provider is optional for read-only consumers, so refresh_graded must
    fail loudly rather than die on an AttributeError against None."""
    service = GradedPriceService(seeded)

    with pytest.raises(RuntimeError, match="without a provider"):
        service.refresh_graded("base1-4")


def test_latest_graded_returns_newest_snapshot(seeded):
    """latest_graded orders by fetched_at DESC, not source_updated_at. The
    newest-FETCHED row here has an OLDER source_updated_at than another row, so
    asserting market == 250.0 only passes under fetched_at-desc ordering — a
    wrong source_updated_at-desc ordering would return the Feb-1 row instead.

    Insert order is the fetch order: market=320/Feb-1 FIRST, then
    market=250/Jan-10 SECOND (later fetched_at, older source stamp).
    """
    quotes = [
        _quote(market=320.0, source_updated_at="2025-02-01"),
        _quote(market=250.0, source_updated_at="2025-01-10"),
    ]
    for q in quotes:
        GradedPriceService(seeded, FakeGradedProvider([q])).refresh_graded("base1-4")

    latest = GradedPriceService(seeded, FakeGradedProvider([])).latest_graded(
        "base1-4", variant="aggregate", grade=10.0, grader="PSA"
    )

    assert latest is not None
    assert latest.market == 250.0
    assert latest.source_updated_at == "2025-01-10"


def test_latest_graded_scopes_to_grader_and_grade(seeded):
    """Asking for PSA 10 must not return a CGC 9.5 snapshot for the same card."""
    GradedPriceService(
        seeded,
        FakeGradedProvider(
            [
                _quote(grader="PSA", grade=10.0, market=275.0, source_updated_at="2025-01-20"),
                _quote(grader="CGC", grade=9.5, market=150.0, source_updated_at="2025-01-20"),
            ]
        ),
    ).refresh_graded("base1-4")

    latest = GradedPriceService(seeded, FakeGradedProvider([])).latest_graded(
        "base1-4", variant="aggregate", grade=10.0, grader="PSA"
    )

    assert latest is not None
    assert latest.grader == "PSA"
    assert latest.grade == 10.0
    assert latest.market == 275.0


def test_latest_graded_defaults_to_psa(seeded):
    """latest_graded's grader default is PSA (the dominant grading service)."""
    GradedPriceService(
        seeded, FakeGradedProvider([_quote(grader="PSA", grade=10.0, market=275.0)])
    ).refresh_graded("base1-4")

    latest = GradedPriceService(seeded, FakeGradedProvider([])).latest_graded(
        "base1-4", variant="aggregate", grade=10.0
    )

    assert latest is not None
    assert latest.grader == "PSA"


def test_latest_graded_returns_none_when_absent(seeded):
    service = GradedPriceService(seeded, FakeGradedProvider([]))
    assert service.latest_graded("base1-4", variant="aggregate", grade=10.0) is None


def test_latest_graded_works_without_a_provider(seeded):
    """The reason the provider is optional: T5's grading-upside endpoint
    constructs GradedPriceService(session) purely to read, never fetch."""
    seeded.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=10.0,
            variant="aggregate",
            market=275.0,
            source="pkmnprices",
            source_updated_at="2025-01-20",
        )
    )
    seeded.commit()

    latest = GradedPriceService(seeded).latest_graded(
        "base1-4", variant="aggregate", grade=10.0, grader="PSA"
    )

    assert latest is not None
    assert latest.market == 275.0


def test_snapshots_are_immutable(seeded):
    """Re-fetching a different price for the SAME source_updated_at does not
    overwrite the existing row — it is silently dropped by dedupe (immutable)."""
    GradedPriceService(
        seeded, FakeGradedProvider([_quote(market=275.0, source_updated_at="2025-01-20")])
    ).refresh_graded("base1-4")
    GradedPriceService(
        seeded, FakeGradedProvider([_quote(market=999.0, source_updated_at="2025-01-20")])
    ).refresh_graded("base1-4")

    rows = seeded.query(GradedPriceSnapshot).all()
    assert len(rows) == 1
    assert rows[0].market == 275.0  # original preserved — not overwritten