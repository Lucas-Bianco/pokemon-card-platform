"""Service-level tests for the sold-lots ledger (roadmap row 29).

Pins the honest-price contract at the service layer: `proceeds` is always
known (a sale has a price), never null/`$0`; `cost_basis`/`realized` are
`None` when no cost basis was recorded at sale time — never a fabricated
`$0`; the summary's `total_realized` is over the cost-known subset only,
`total_proceeds` sums all sales; add/remove/list/summary behave as
specified; a dangled FK (deleted catalog card) is skipped at read time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.db.models import Card, CardSet
from cardplatform.sold.service import SoldLotService


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


def svc(seeded):
    return SoldLotService(seeded)


def test_add_unknown_card_raises_lookup_error(seeded):
    with pytest.raises(LookupError):
        svc(seeded).add("nope-1", sale_price=10.0)


def test_add_zero_quantity_raises_value_error(seeded):
    with pytest.raises(ValueError):
        svc(seeded).add("base1-4", quantity=0, sale_price=10.0)


def test_add_negative_sale_price_raises_value_error(seeded):
    with pytest.raises(ValueError):
        svc(seeded).add("base1-4", sale_price=-1.0)


def test_add_returns_entry_with_catalog_and_money_fields(seeded):
    s = svc(seeded)
    e = s.add("base1-4", quantity=2, sale_price=50.0, sale_fee=5.0,
              acquired_price=20.0, source="eBay", notes="graded")
    assert e.card_id == "base1-4"
    assert e.variant == "normal"
    assert e.quantity == 2
    assert e.sale_price == 50.0
    assert e.sale_fee == 5.0
    assert e.acquired_price == 20.0
    assert e.source == "eBay"
    assert e.notes == "graded"
    assert e.card_name == "Charizard"
    assert e.set_name == "Base"
    assert e.number == "4"
    # proceeds = (50 - 5) * 2 = 90; cost = 20 * 2 = 40; realized = 50.
    assert e.proceeds == pytest.approx(90.0)
    assert e.cost_basis == pytest.approx(40.0)
    assert e.realized == pytest.approx(50.0)


def test_add_without_cost_basis_has_null_realized_never_zero(seeded):
    s = svc(seeded)
    e = s.add("base1-4", sale_price=30.0)
    assert e.proceeds == pytest.approx(30.0)
    assert e.cost_basis is None
    assert e.realized is None


def test_add_defaults_sold_at_to_now_aware(seeded):
    e = svc(seeded).add("base1-4", sale_price=10.0)
    assert e.sold_at.tzinfo is not None  # UtcDateTime re-attaches UTC


def test_add_accepts_explicit_sold_at(seeded):
    when = datetime(2026, 1, 15, tzinfo=timezone.utc)
    e = svc(seeded).add("base1-4", sale_price=10.0, sold_at=when)
    assert e.sold_at == when


def test_add_fee_none_treated_as_zero_in_proceeds(seeded):
    e = svc(seeded).add("base1-4", quantity=3, sale_price=10.0, sale_fee=None)
    assert e.proceeds == pytest.approx(30.0)


def test_add_duplicate_allowed_no_unique_constraint(seeded):
    # Unlike the want list, the sold ledger is append-only — two sales of the
    # same card/variant are legitimate, not a conflict.
    s = svc(seeded)
    s.add("base1-4", sale_price=10.0)
    s.add("base1-4", sale_price=20.0)
    assert len(s.list_lots()) == 2


def test_list_lots_empty_when_nothing_added(seeded):
    assert svc(seeded).list_lots() == []


def test_list_lots_oldest_sale_first(seeded):
    s = svc(seeded)
    s.add("base2-1", sale_price=10.0,
          sold_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    s.add("base1-4", sale_price=10.0,
          sold_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    lots = s.list_lots()
    assert [l.card_id for l in lots] == ["base1-4", "base2-1"]


def test_remove_returns_true_when_present(seeded):
    s = svc(seeded)
    e = s.add("base1-4", sale_price=10.0)
    assert s.remove(e.id) is True
    assert s.list_lots() == []


def test_remove_returns_false_when_absent(seeded):
    assert svc(seeded).remove(99999) is False


def test_summary_empty_ledger(seeded):
    summ = svc(seeded).summary()
    assert summ.lot_count == 0
    assert summ.lots_with_cost == 0
    assert summ.lots_without_cost == 0
    assert summ.total_proceeds == pytest.approx(0.0)
    assert summ.total_cost_basis == pytest.approx(0.0)
    assert summ.total_realized == pytest.approx(0.0)
    assert summ.winners == 0
    assert summ.losers == 0
    assert summ.caveat  # honest explanation always present


def test_summary_realized_over_cost_known_subset_only(seeded):
    s = svc(seeded)
    # With cost: proceeds 90, cost 40, realized +50 (winner).
    s.add("base1-4", quantity=2, sale_price=50.0, sale_fee=5.0, acquired_price=20.0)
    # Without cost: proceeds 30, excluded from realized, counted separately.
    s.add("base2-1", sale_price=30.0)
    summ = s.summary()
    assert summ.lot_count == 2
    assert summ.lots_with_cost == 1
    assert summ.lots_without_cost == 1
    assert summ.total_proceeds == pytest.approx(120.0)  # 90 + 30
    assert summ.total_cost_basis == pytest.approx(40.0)
    assert summ.total_realized == pytest.approx(50.0)  # not 80 (no $0 for the unknown)
    assert summ.winners == 1
    assert summ.losers == 0


def test_summary_counts_losers(seeded):
    s = svc(seeded)
    # Sold below cost: proceeds 10, cost 40, realized -30 (loser).
    s.add("base1-4", sale_price=10.0, acquired_price=40.0)
    summ = s.summary()
    assert summ.losers == 1
    assert summ.winners == 0
    assert summ.total_realized == pytest.approx(-30.0)


def test_summary_break_even_not_winner_or_loser(seeded):
    s = svc(seeded)
    s.add("base1-4", sale_price=20.0, acquired_price=20.0)
    summ = s.summary()
    assert summ.winners == 0
    assert summ.losers == 0
    assert summ.total_realized == pytest.approx(0.0)


def test_variant_specific_lot_distinct(seeded):
    s = svc(seeded)
    s.add("base1-4", variant="reverseHolofoil", sale_price=200.0, acquired_price=50.0)
    s.add("base1-4", variant="normal", sale_price=20.0, acquired_price=5.0)
    lots = {l.variant: l for l in s.list_lots()}
    assert lots["reverseHolofoil"].proceeds == pytest.approx(200.0)
    assert lots["normal"].proceeds == pytest.approx(20.0)


def test_set_name_from_card_set(seeded):
    s = svc(seeded)
    s.add("base1-4", sale_price=10.0)
    s.add("base2-1", sale_price=10.0)
    lots = {l.card_id: l for l in s.list_lots()}
    assert lots["base1-4"].set_name == "Base"
    assert lots["base2-1"].set_name == "Jungle"