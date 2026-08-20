from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from cardplatform.db.models import SealedPurchase, SealedValuation
from cardplatform.sealed.ledger import (
    LedgerEntry,
    LedgerService,
    ValuationRefreshResult,
    build_sheet_rows,
)
from cardplatform.sealed.provider import SealedSoldComp


@dataclass
class FakeProvider:
    name: str = "fake"
    comps_by_query: dict = None
    raise_on_call: bool = False

    def __post_init__(self):
        if self.comps_by_query is None:
            self.comps_by_query = {}

    def fetch_listings_by_query(self, query):
        return []

    def fetch_sold_listings_by_query(self, query, limit=3):
        if self.raise_on_call:
            raise RuntimeError("provider blew up")
        return list(self.comps_by_query.get(query, []))


def _comp(price, listing_id="c1"):
    return SealedSoldComp(query="q", listing_id=listing_id, price=price)


def _service(db, provider=None, settings=None):
    return LedgerService(db, provider=provider or FakeProvider(), settings=settings)


def test_create_purchase_validates_inputs(db):
    svc = _service(db)
    with pytest.raises(ValueError):
        svc.create_purchase(query="", cost_per_unit=10.0)
    with pytest.raises(ValueError):
        svc.create_purchase(query="box", quantity=0, cost_per_unit=10.0)
    with pytest.raises(ValueError):
        svc.create_purchase(query="box", cost_per_unit=-1.0)


def test_create_purchase_persists_and_returns(db):
    svc = _service(db)
    p = svc.create_purchase(
        query="scarlet violet booster box",
        product_type="booster_box",
        quantity=2,
        cost_per_unit=120.0,
        source="eBay",
    )
    assert p.id is not None
    assert p.quantity == 2
    assert db.get(SealedPurchase, p.id).query == "scarlet violet booster box"


def test_delete_purchase_removes_valuations_too(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", cost_per_unit=10.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=12.0, comp_count=3))
    db.commit()
    assert svc.delete_purchase(p.id) is True
    assert db.get(SealedPurchase, p.id) is None
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 0


def test_delete_missing_purchase_returns_false(db):
    svc = _service(db)
    assert svc.delete_purchase(999) is False


def test_list_ledger_computes_profit_from_latest_valuation(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", quantity=2, cost_per_unit=100.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=130.0, comp_count=5))
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=150.0, comp_count=6))  # latest
    db.commit()
    entries = svc.list_ledger()
    assert len(entries) == 1
    e = entries[0]
    assert e.total_cost == 200.0
    assert e.value_per_unit == 150.0  # latest = max(id)
    assert e.total_current_value == 300.0
    assert e.profit == 100.0
    assert e.profit_pct == 0.5
    assert e.valued is True
    assert e.market_source == "ebay_sold_median"


def test_list_ledger_unvalued_purchase_has_nulls_never_zero(db):
    svc = _service(db)
    svc.create_purchase(query="box", quantity=1, cost_per_unit=100.0)
    e = svc.list_ledger()[0]
    assert e.value_per_unit is None
    assert e.total_current_value is None
    assert e.profit is None
    assert e.profit_pct is None
    assert e.valued is False
    assert e.total_cost == 100.0  # cost is known


def test_list_ledger_profit_pct_null_when_cost_zero(db):
    svc = _service(db)
    p = svc.create_purchase(query="gift", quantity=1, cost_per_unit=0.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=10.0, comp_count=2))
    db.commit()
    e = svc.list_ledger()[0]
    assert e.profit == 10.0
    assert e.profit_pct is None  # division by zero guarded


def test_refresh_valuation_inserts_median_snapshot(db):
    provider = FakeProvider(comps_by_query={"box": [_comp(60.0), _comp(64.0), _comp(70.0)]})
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    v = svc.refresh_valuation(p.id)
    assert v is not None
    assert v.value_per_unit == 64.0  # median of [60,64,70]
    assert v.comp_count == 3
    assert v.source == "ebay_sold_median"
    # append-only: a second refresh adds a second row
    v2 = svc.refresh_valuation(p.id)
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 2


def test_refresh_valuation_no_comps_returns_none_no_row(db):
    provider = FakeProvider(comps_by_query={"box": []})
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    assert svc.refresh_valuation(p.id) is None
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 0


def test_refresh_valuation_provider_raises_degrades_to_none(db):
    provider = FakeProvider(raise_on_call=True)
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    # The real provider never raises; a fake that does must still not blow up the service.
    assert svc.refresh_valuation(p.id) is None


def test_refresh_all_summarizes_valued_and_skipped(db):
    provider = FakeProvider(
        comps_by_query={
            "box": [_comp(60.0), _comp(64.0)],          # valued
            "pack": [],                                  # no comps -> skipped
        }
    )
    svc = _service(db, provider=provider)
    svc.create_purchase(query="box", cost_per_unit=50.0)
    svc.create_purchase(query="pack", cost_per_unit=5.0)
    result = svc.refresh_all()
    assert isinstance(result, ValuationRefreshResult)
    assert result.valued == 1
    assert result.skipped_no_comps == 1
    assert result.skipped_no_key is False


# --------------------------------------------------------------- build_sheet_rows (T7)


def test_build_sheet_rows_header_and_nulls_to_blank(db):
    svc = _service(db)
    svc.create_purchase(query="box", quantity=1, cost_per_unit=100.0)  # unvalued
    rows = build_sheet_rows(svc.list_ledger())
    assert rows[0][0] == "Date"
    assert rows[0][7] == "Total Value"
    row = rows[1]
    assert row[1] == "box"
    assert row[6] == ""   # market/unit blank (unvalued)
    assert row[8] == ""   # profit blank
    assert row[9] == ""   # profit % blank
    assert row[5] == "100.00"  # total cost known


def test_build_sheet_rows_valued_entry_filled(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", quantity=2, cost_per_unit=100.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=150.0, comp_count=4))
    db.commit()
    rows = build_sheet_rows(svc.list_ledger())
    row = rows[1]
    assert row[6] == "150.00"  # market/unit
    assert row[7] == "300.00"  # total value
    assert row[8] == "100.00"  # profit
    assert row[9] == "50%"     # profit %