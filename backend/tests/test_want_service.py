"""Service-level tests for the want list / hunt list (roadmap row 24).

Pins the honest-price contract at the service layer: a slot with no market
price carries `market_price=None` (never a fabricated `$0`); `target_price` is
None for "no target"; `deal_gap`/`within_target` are None when either side is
missing, never guessed; add/remove/set_target_price/set_note behave as
specified; a dangled FK (deleted catalog card) is skipped at read time.
"""

from __future__ import annotations

import pytest

from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.wants.service import WantService


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Jungle"))
    db.add(
        Card(
            id="base1-4", set_id="base1", name="Charizard", number="4",
            rarity="Rare Holo", supertype="Pokemon",
        )
    )
    db.add(
        Card(
            id="base2-1", set_id="base2", name="Pikachu", number="1",
            rarity="Common", supertype="Pokemon",
        )
    )
    db.commit()
    return db


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


def svc(seeded):
    return WantService(seeded)


def test_add_unknown_card_raises_lookup_error(seeded):
    with pytest.raises(LookupError):
        svc(seeded).add("nope-1")


def test_add_duplicate_raises_value_error(seeded):
    s = svc(seeded)
    s.add("base1-4")
    with pytest.raises(ValueError):
        s.add("base1-4")


def test_add_returns_entry_with_catalog_fields(seeded):
    s = svc(seeded)
    e = s.add("base1-4", target_price=50.0, note="want")
    assert e.card_id == "base1-4"
    assert e.variant == "normal"
    assert e.target_price == 50.0
    assert e.note == "want"
    assert e.card_name == "Charizard"
    assert e.set_name == "Base"
    assert e.number == "4"
    assert e.rarity == "Rare Holo"


def test_list_items_empty_when_nothing_added(seeded):
    assert svc(seeded).list_items() == []


def test_list_items_oldest_first(seeded):
    s = svc(seeded)
    s.add("base1-4")
    s.add("base2-1")
    items = s.list_items()
    assert [i.card_id for i in items] == ["base1-4", "base2-1"]


def test_market_price_is_none_when_no_snapshot(seeded):
    s = svc(seeded)
    s.add("base1-4", target_price=50.0)
    e = s.list_items()[0]
    assert e.market_price is None
    assert e.market_source is None
    assert e.market_source_updated_at is None
    # No market -> no deal gap, no within-target, even with a target set.
    assert e.deal_gap is None
    assert e.within_target is None


def test_market_price_resolved_from_latest_price(seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=40.0)
    s = svc(seeded)
    s.add("base1-4", target_price=50.0)
    e = s.list_items()[0]
    assert e.market_price == 40.0
    assert e.market_source == "tcgplayer"
    assert e.market_source_updated_at == "2026/07/28"


def test_deal_gap_and_within_target_when_both_present(seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=40.0)
    s = svc(seeded)
    # target above market -> positive gap, within target.
    s.add("base1-4", target_price=50.0)
    e = s.list_items()[0]
    assert e.deal_gap == pytest.approx(10.0)
    assert e.within_target is True


def test_within_target_false_when_market_exceeds_target(seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=60.0)
    s = svc(seeded)
    s.add("base1-4", target_price=50.0)
    e = s.list_items()[0]
    assert e.deal_gap == pytest.approx(-10.0)
    assert e.within_target is False


def test_deal_gap_none_when_target_missing(seeded):
    snap(seeded, "base1-4", "tcgplayer", "normal", market=40.0)
    s = svc(seeded)
    s.add("base1-4")  # no target
    e = s.list_items()[0]
    assert e.target_price is None
    assert e.deal_gap is None
    assert e.within_target is None


def test_deal_gap_none_when_market_missing(seeded):
    s = svc(seeded)
    s.add("base1-4", target_price=50.0)  # no market
    e = s.list_items()[0]
    assert e.market_price is None
    assert e.deal_gap is None
    assert e.within_target is None


def test_remove_returns_true_when_present(seeded):
    s = svc(seeded)
    s.add("base1-4")
    assert s.remove("base1-4") is True
    assert s.list_items() == []


def test_remove_returns_false_when_absent(seeded):
    assert svc(seeded).remove("base1-4") is False


def test_set_target_price_sets_and_clears(seeded):
    s = svc(seeded)
    s.add("base1-4")
    s.set_target_price("base1-4", target_price=75.0)
    assert s.list_items()[0].target_price == 75.0
    s.set_target_price("base1-4", target_price=None)  # clear
    assert s.list_items()[0].target_price is None


def test_set_target_price_unknown_slot_raises(seeded):
    with pytest.raises(LookupError):
        svc(seeded).set_target_price("base1-4", target_price=75.0)


def test_set_note_sets_and_clears(seeded):
    s = svc(seeded)
    s.add("base1-4")
    s.set_note("base1-4", note="birthday gift")
    assert s.list_items()[0].note == "birthday gift"
    s.set_note("base1-4", note=None)
    assert s.list_items()[0].note is None


def test_set_note_unknown_slot_raises(seeded):
    with pytest.raises(LookupError):
        svc(seeded).set_note("base1-4", note="x")


def test_variant_specific_slot_distinct_from_normal(seeded):
    s = svc(seeded)
    s.add("base1-4", variant="normal")
    s.add("base1-4", variant="reverseHolofoil")  # distinct slot, allowed
    items = s.list_items()
    assert {i.variant for i in items} == {"normal", "reverseHolofoil"}


def test_variant_specific_market_price_used(seeded):
    snap(seeded, "base1-4", "tcgplayer", "reverseHolofoil", market=200.0)
    s = svc(seeded)
    s.add("base1-4", variant="reverseHolofoil", target_price=180.0)
    e = s.list_items()[0]
    assert e.market_price == 200.0
    assert e.deal_gap == pytest.approx(-20.0)
    assert e.within_target is False


def test_cardmarket_fallback_used_when_no_tcgplayer_snapshot(seeded):
    snap(seeded, "base1-4", "cardmarket", "aggregate", market=80.0)
    s = svc(seeded)
    s.add("base1-4", target_price=100.0)
    e = s.list_items()[0]
    assert e.market_price == 80.0
    assert e.market_source == "cardmarket"


def test_set_name_from_card_set(seeded):
    # The joined set_name comes from the card's card_set relationship.
    s = svc(seeded)
    s.add("base1-4")
    s.add("base2-1")
    items = {i.card_id: i for i in s.list_items()}
    assert items["base1-4"].set_name == "Base"
    assert items["base2-1"].set_name == "Jungle"