"""Service-level tests for the shareable binder (roadmap row 21).

Pins the honest-price contract at the service layer: a slot with no proven sale
is `proven_sale=None` (never a fabricated `$0`); `proven_sale_unavailable`
flags a keyless server and `proven_sale_empty` a key set but no comps; the
provider degrades to [] and never raises; add/remove/reorder/note behave as
specified; export_html is self-contained HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.binder.service import BinderService
from cardplatform.db.models import BinderItem, Card, CardSet
from cardplatform.prices.listings_provider import SoldComp


class StubProvider:
    """Stands in for EbayListingsProvider. Returns fixed comps per (card_id,
    variant); an empty list (not a raise) models 'no comps'. Records calls."""

    def __init__(self, comps_by_key: dict | None = None) -> None:
        self.comps_by_key = comps_by_key or {}
        self.calls: list[tuple[str, str, int]] = []

    def fetch_sold_listings(self, card_id, variant, limit=3):
        self.calls.append((card_id, variant, limit))
        return list(self.comps_by_key.get((card_id, variant), []))


def _comp(price: float, card_id="base1-4", variant="normal"):
    return SoldComp(
        card_id=card_id,
        variant=variant,
        listing_id=f"l{price}",
        price=price,
        title="Charizard",
        currency="USD",
        sold_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        condition="Raw",
    )


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Jungle"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", rarity="Rare Holo"))
    db.add(Card(id="base2-1", set_id="base2", name="Pikachu", number="1", rarity="Common"))
    db.commit()
    return db


def service(db, comps=None, key_set=True):
    return BinderService(db, sold_comps_provider=StubProvider(comps or {}), listings_api_key_set=key_set)


def test_add_unknown_card_raises_lookup_error(seeded):
    svc = service(seeded)
    with pytest.raises(LookupError):
        svc.add("nope-1")


def test_add_appends_at_end_with_increasing_sort_order(seeded):
    svc = service(seeded)
    a = svc.add("base1-4", note="first")
    b = svc.add("base2-1")
    assert a.sort_order == 1
    assert b.sort_order == 2
    # Two distinct slots, unique (card_id, variant).
    assert a.card_id == "base1-4" and b.card_id == "base2-1"


def test_add_duplicate_slot_raises_value_error(seeded):
    svc = service(seeded)
    svc.add("base1-4")
    with pytest.raises(ValueError):
        svc.add("base1-4")


def test_add_same_card_different_variant_is_separate_slot(seeded):
    svc = service(seeded)
    svc.add("base1-4", variant="normal")
    svc.add("base1-4", variant="reverseHolofoil")  # different slot, no error
    entries = svc.list_items()
    assert len(entries) == 2


def test_remove_returns_true_then_false(seeded):
    svc = service(seeded)
    svc.add("base1-4")
    assert svc.remove("base1-4") is True
    assert svc.remove("base1-4") is False  # already gone


def test_set_note_sets_clears_and_raises_for_unknown_slot(seeded):
    svc = service(seeded)
    svc.add("base1-4")
    item = svc.set_note("base1-4", note="grail")
    assert item.note == "grail"
    item = svc.set_note("base1-4", note=None)  # clear
    assert item.note is None
    with pytest.raises(LookupError):
        svc.set_note("base2-1", note="x")  # not in binder


def test_list_items_orders_by_sort_order_and_joins_catalog(seeded):
    svc = service(seeded)
    svc.add("base2-1")  # sort_order 1
    svc.add("base1-4")  # sort_order 2
    entries = svc.list_items()
    # Insertion order honored by sort_order: base2-1 first, base1-4 second.
    assert [e.card_id for e in entries] == ["base2-1", "base1-4"]
    # Catalog row joined in.
    z = next(e for e in entries if e.card_id == "base1-4")
    assert z.card_name == "Charizard"
    assert z.set_name == "Base"
    assert z.number == "4"
    assert z.rarity == "Rare Holo"
    assert z.variant == "normal"


def test_list_items_attaches_proven_sale_when_provider_has_comps(seeded):
    comps = {("base1-4", "normal"): [_comp(118.0)]}
    svc = service(seeded, comps=comps)
    svc.add("base1-4")
    entries = svc.list_items()
    e = entries[0]
    assert e.proven_sale is not None
    assert e.proven_sale.price == 118.0
    assert e.proven_sale.currency == "USD"
    assert e.proven_sale_unavailable is False
    assert e.proven_sale_empty is False
    # Provider asked for at most 1 comp (limit=1) — cheapest read that still proves.
    assert svc.sold_comps.calls[-1] == ("base1-4", "normal", 1)


def test_list_items_honest_empty_when_key_set_but_no_comps(seeded):
    # Provider present, key set, but no comps for this card -> empty (not unavailable).
    svc = service(seeded, comps={}, key_set=True)
    svc.add("base1-4")
    e = svc.list_items()[0]
    assert e.proven_sale is None
    assert e.proven_sale_unavailable is False
    assert e.proven_sale_empty is True


def test_list_items_honest_unavailable_when_no_key(seeded):
    # No key configured -> unavailable (so UI says "set a key", not "no sales").
    svc = service(seeded, comps={}, key_set=False)
    svc.add("base1-4")
    e = svc.list_items()[0]
    assert e.proven_sale is None
    assert e.proven_sale_unavailable is True
    assert e.proven_sale_empty is False


def test_list_items_with_no_provider_is_unavailable(seeded):
    # No provider wired at all (keyless server) -> unavailable, never raises.
    svc = BinderService(seeded, sold_comps_provider=None, listings_api_key_set=False)
    svc.add("base1-4")
    e = svc.list_items()[0]
    assert e.proven_sale is None
    assert e.proven_sale_unavailable is True
    assert e.proven_sale_empty is False


def test_reorder_named_slots_first_unnamed_keep_relative_order(seeded):
    svc = service(seeded)
    svc.add("base1-4")  # sort 1
    svc.add("base2-1")  # sort 2
    # Add a third card so we can test unnamed-slot survival.
    seeded.add(Card(id="base1-1", set_id="base1", name="Energy Retreiver", number="1"))
    seeded.commit()
    svc.add("base1-1")  # sort 3
    # Reorder: name base2-1 first, then base1-4. base1-1 not named -> appended after.
    svc.reorder([("base2-1", "normal"), ("base1-4", "normal")])
    entries = svc.list_items()
    assert [e.card_id for e in entries] == ["base2-1", "base1-4", "base1-1"]
    assert [e.sort_order for e in entries] == [0, 1, 2]


def test_reorder_unknown_keys_ignored(seeded):
    svc = service(seeded)
    svc.add("base1-4")
    svc.add("base2-1")
    svc.reorder([("nope", "normal"), ("base2-1", "normal"), ("base1-4", "normal")])
    assert [e.card_id for e in svc.list_items()] == ["base2-1", "base1-4"]


def test_reorder_dedupe_keeps_last_position(seeded):
    svc = service(seeded)
    svc.add("base1-4")
    svc.add("base2-1")
    # base1-4 listed twice; last occurrence should win (position 1, after base2-1).
    svc.reorder([("base1-4", "normal"), ("base2-1", "normal"), ("base1-4", "normal")])
    assert [e.card_id for e in svc.list_items()] == ["base2-1", "base1-4"]


def test_remove_does_not_renumber_surviving_slots(seeded):
    svc = service(seeded)
    svc.add("base1-4")  # sort 1
    svc.add("base2-1")  # sort 2
    svc.remove("base1-4")
    entries = svc.list_items()
    assert [e.card_id for e in entries] == ["base2-1"]
    # base2-1 keeps sort_order 2 (gap at 1 is harmless — list orders by sort_order).
    assert entries[0].sort_order == 2


def test_export_html_is_self_contained_and_honest(seeded):
    comps = {("base1-4", "normal"): [_comp(118.0)]}
    svc = service(seeded, comps=comps)
    svc.add("base1-4", note="grail")
    svc.add("base2-1")  # no comps -> "no proven sale yet"
    doc = svc.export_html(title="My PC")
    # Self-contained: inline <style>, no external CSS link.
    assert "<style>" in doc
    assert "<link" not in doc
    # Title + count baked in.
    assert "My PC" in doc
    assert "2 card(s)" in doc
    # The proven card shows its price; the no-comp card shows the honest empty.
    assert "118" in doc  # 118.00 stripped to 118
    assert "no proven sale yet" in doc.lower()
    # The note is rendered.
    assert "grail" in doc
    # Card names present.
    assert "Charizard" in doc
    assert "Pikachu" in doc