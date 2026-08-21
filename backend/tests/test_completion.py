from __future__ import annotations

import pytest

from cardplatform.catalog.completion import CompletionService
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot
from cardplatform.prices.service import PriceService


@pytest.fixture
def seeded(db):
    # Two sets. base1 has plain numeric numbers + a suffixed promo. promo1 has a
    # non-numeric prefix (TG01) that must sort after the plain numerics.
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09", total=3))
    db.add(CardSet(id="promo1", name="Promo", series="Promo", release_date="2020/01/01", total=1))
    db.add(Card(id="base1-1", set_id="base1", name="Bulbasaur", number="1", rarity="Common"))
    db.add(Card(id="base1-10", set_id="base1", name="Pikachu", number="10", rarity="Common"))
    db.add(Card(id="base1-4a", set_id="base1", name="Snap Promo", number="4a", rarity="Promo"))
    db.add(Card(id="promo1-1", set_id="promo1", name="Mew Promo", number="TG01", rarity="Promo"))
    db.commit()
    return db


def snap(db, card_id, market, source="tcgplayer", variant="normal", stamp="2026/07/28"):
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant, market=market, source_updated_at=stamp
        )
    )
    db.commit()


@pytest.fixture
def service(seeded):
    return CompletionService(seeded, PriceService(seeded))


def test_list_sets_orders_by_release_date_desc_and_counts_owned(service, seeded):
    # Own one card in base1 (any variant counts as owned).
    seeded.add(CollectionItem(card_id="base1-10", variant="holofoil", quantity=1))
    seeded.commit()
    sets = service.list_sets()
    assert [s.id for s in sets] == ["promo1", "base1"]  # newer first
    base1 = next(s for s in sets if s.id == "base1")
    assert base1.checklist_size == 3
    assert base1.owned == 1
    assert base1.pct_complete == pytest.approx(1 / 3)
    promo = next(s for s in sets if s.id == "promo1")
    assert promo.owned == 0
    assert promo.pct_complete == 0  # honest 0%, never fabricated


def test_list_sets_filter_uses_lower_like_not_ilike(service):
    sets = service.list_sets(query="base")
    assert [s.id for s in sets] == ["base1"]
    # Case-insensitive via func.lower().like(); this confirms the path.
    assert service.list_sets(query="PROMO")[0].id == "promo1"


def test_list_sets_zero_cards_does_not_divide_by_zero(db):
    db.add(CardSet(id="empty", name="Empty", series="X", release_date="2024/01/01"))
    db.commit()
    svc = CompletionService(db, PriceService(db))
    s = svc.list_sets()[0]
    assert s.checklist_size == 0
    assert s.pct_complete == 0


def test_set_detail_natural_sort_numeric_then_suffix_then_prefix(service):
    detail = service.set_detail("base1")
    numbers = [c.number for c in detail.cards]
    # 1, then 4a (suffix of 4, sorts right after plain numerics < 10), then 10.
    # TG01 lives in promo1, not here.
    assert numbers == ["1", "4a", "10"]


def test_set_detail_owned_flags_and_missing_prices(service, seeded):
    snap(seeded, "base1-1", market=2.0)  # priced missing
    seeded.add(CollectionItem(card_id="base1-10", variant="normal", quantity=1))
    seeded.commit()
    detail = service.set_detail("base1")
    by_id = {c.card_id: c for c in detail.cards}
    assert by_id["base1-10"].owned is True          # owned
    assert by_id["base1-10"].market is None         # owned cards are not priced
    assert by_id["base1-1"].owned is False
    assert by_id["base1-1"].market == 2.0           # via latest_price
    assert by_id["base1-1"].source == "tcgplayer"
    assert by_id["base1-1"].source_updated_at == "2026/07/28"
    assert by_id["base1-4a"].owned is False
    assert by_id["base1-4a"].market is None          # unpriced missing


def test_set_detail_summary_honest_costs(service, seeded):
    snap(seeded, "base1-1", market=2.0)
    snap(seeded, "base1-10", market=5.0)
    seeded.commit()
    detail = service.set_detail("base1")  # own nothing -> 3 missing, 2 priced
    s = detail.summary
    assert s.owned == 0
    assert s.checklist_size == 3
    assert s.missing == 3
    assert s.pct_complete == 0
    assert s.est_cost_to_complete == 7.0     # 2.0 + 5.0
    assert s.unpriced_missing == 1           # base1-4a


def test_set_detail_summary_none_when_all_missing_unpriced(service):
    detail = service.set_detail("base1")  # no snapshots at all
    s = detail.summary
    assert s.est_cost_to_complete is None  # never 0.0 when nothing is priced
    assert s.unpriced_missing == 3


def test_set_detail_summary_zero_when_complete(service, seeded):
    for cid in ("base1-1", "base1-10", "base1-4a"):
        seeded.add(CollectionItem(card_id=cid, variant="normal", quantity=1))
    seeded.commit()
    s = service.set_detail("base1").summary
    assert s.missing == 0
    assert s.est_cost_to_complete == 0.0   # complete -> $0 to finish is honest
    assert s.unpriced_missing == 0


def test_set_detail_unknown_set_raises(service):
    with pytest.raises(LookupError):
        service.set_detail("nope")


def test_latest_price_empty_string_stamp_becomes_none_on_wire(service, seeded):
    snap(seeded, "base1-1", market=2.0, stamp="")  # "" sentinel
    seeded.commit()
    detail = service.set_detail("base1")
    entry = next(c for c in detail.cards if c.card_id == "base1-1")
    assert entry.source_updated_at is None  # "" -> None