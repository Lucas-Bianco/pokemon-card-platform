import pytest

from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.prices.provider import PriceQuote
from cardplatform.prices.service import PriceService


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


def test_latest_price_prefers_tcgplayer(seeded):
    quotes = [
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
        PriceQuote("base1-4", "cardmarket", "aggregate", market=2.67, source_updated_at="2026/07/01"),
    ]
    service = PriceService(seeded, FakeProvider(quotes))
    service.refresh_card("base1-4")

    latest = service.latest_price("base1-4", variant="holofoil")

    assert latest.source == "tcgplayer"
    assert latest.market == 9.71


def test_latest_price_returns_none_when_unpriced(seeded):
    service = PriceService(seeded, FakeProvider([]))
    assert service.latest_price("base1-4", variant="holofoil") is None
