from __future__ import annotations

import pytest
from sqlalchemy import select

from cardplatform.cards.lookup import CardLookupService
from cardplatform.db.models import Card, CardSet, PriceSnapshot


class FakePriceService:
    """Stand-in for PriceService so the lookup test stays isolated from the
    price-refresh path. latest_price returns a snapshot if one was seeded for
    the card, else None — mirroring the real service's contract."""

    def __init__(self, session):
        self.session = session

    def latest_price(self, card_id, variant):
        # Return the newest seeded snapshot for this card/variant, else None.
        return self.session.scalars(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.variant == variant,
            )
            .order_by(PriceSnapshot.fetched_at.desc(), PriceSnapshot.id.desc())
            .limit(1)
        ).first()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09"))
    db.add(CardSet(id="swsh1", name="Sword & Shield", series="Sword & Shield"))
    db.add(
        Card(
            id="base1-1",
            set_id="base1",
            name="Bulbasaur",
            number="1",
            rarity="Common",
            image_small="s1",
            image_large="l1",
        )
    )
    db.add(
        Card(
            id="base1-2",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            image_small="s2",
            image_large="l2",
        )
    )
    db.add(
        Card(
            id="swsh1-1",
            set_id="swsh1",
            name="Charizard VMAX",
            number="1",
            rarity="Rare Holo",
            image_small="s3",
            image_large="l3",
        )
    )
    db.commit()
    return db


def snap(db, card_id, market, source="tcgplayer", variant="normal", stamp="2026/07/28"):
    db.add(
        PriceSnapshot(
            card_id=card_id,
            source=source,
            variant=variant,
            market=market,
            source_updated_at=stamp,
        )
    )
    db.commit()


@pytest.fixture
def service(seeded):
    return CardLookupService(seeded, FakePriceService(seeded))


def test_substring_match_returns_matching_cards(service, seeded):
    results = service.lookup("bulb")
    assert [r["card_id"] for r in results] == ["base1-1"]
    r = results[0]
    assert r["name"] == "Bulbasaur"
    assert r["set_id"] == "base1"
    assert r["set_name"] == "Base"
    assert r["number"] == "1"
    assert r["rarity"] == "Common"
    assert r["image_small"] == "s1"
    assert r["image_large"] == "l1"


def test_card_with_price_snapshot_attaches_market_and_source(service, seeded):
    snap(seeded, "base1-1", market=2.5, source="tcgplayer", stamp="2026/08/01")
    results = service.lookup("bulb")
    r = results[0]
    assert r["market"] == 2.5
    assert r["source"] == "tcgplayer"
    assert r["source_updated_at"] == "2026/08/01"


def test_card_with_no_snapshot_has_market_none_not_zero(service, seeded):
    results = service.lookup("bulb")
    r = results[0]
    assert r["market"] is None  # NEVER 0
    assert r["source"] is None
    assert r["source_updated_at"] is None


def test_query_shorter_than_two_chars_returns_empty(service):
    assert service.lookup("a") == []
    assert service.lookup("") == []
    assert service.lookup(" ") == []  # whitespace-only strips to ""


def test_no_matches_returns_empty(service):
    assert service.lookup("mewtwo") == []


def test_case_insensitive_match(service, seeded):
    # 'char' matches both 'Charizard' and 'Charizard VMAX', ordered by name.
    results = service.lookup("char")
    names = [r["name"] for r in results]
    assert "Charizard" in names
    assert "Charizard VMAX" in names


def test_case_insensitive_uppercase_query_matches(service, seeded):
    results = service.lookup("CHAR")
    assert [r["card_id"] for r in results] == ["base1-2", "swsh1-1"]


def test_limit_caps_results(service, seeded):
    # 'char' matches two cards; limit=1 returns only the first by name.
    results = service.lookup("char", limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "Charizard"


def test_empty_string_stamp_becomes_none_on_wire(service, seeded):
    snap(seeded, "base1-1", market=3.0, stamp="")  # "" sentinel
    results = service.lookup("bulb")
    r = results[0]
    assert r["market"] == 3.0
    assert r["source"] == "tcgplayer"
    assert r["source_updated_at"] is None  # "" -> None, mirrors set_detail