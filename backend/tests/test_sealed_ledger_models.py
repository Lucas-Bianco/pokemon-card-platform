from datetime import datetime, timezone

from cardplatform.db.models import SealedPurchase, SealedValuation


def test_can_persist_a_purchase(db):
    p = SealedPurchase(
        query="scarlet violet booster box",
        product_type="booster_box",
        quantity=2,
        cost_per_unit=120.0,
        source="eBay",
        listing_url="https://example.com/x",
        notes="sealed case",
        bought_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )
    db.add(p)
    db.commit()
    got = db.get(SealedPurchase, p.id)
    assert got is not None
    assert got.query == "scarlet violet booster box"
    assert got.quantity == 2
    assert got.cost_per_unit == 120.0
    assert got.created_at.tzinfo is not None  # UtcDateTime re-attaches UTC


def test_purchase_defaults_quantity_and_timestamps(db):
    p = SealedPurchase(query="pokemon 151 booster bundle", cost_per_unit=27.5)
    db.add(p)
    db.commit()
    got = db.get(SealedPurchase, p.id)
    assert got.quantity == 1
    assert got.product_type is None
    assert got.bought_at is not None and got.bought_at.tzinfo is not None
    assert got.created_at.tzinfo is not None


def test_can_persist_a_valuation_and_latest_is_max_id(db):
    p = SealedPurchase(query="etb", cost_per_unit=50.0)
    db.add(p)
    db.commit()
    v1 = SealedValuation(purchase_id=p.id, value_per_unit=60.0, comp_count=5)
    v2 = SealedValuation(purchase_id=p.id, value_per_unit=64.0, comp_count=6)
    db.add_all([v1, v2])
    db.commit()
    rows = (
        db.query(SealedValuation)
        .filter(SealedValuation.purchase_id == p.id)
        .order_by(SealedValuation.id.desc())
        .all()
    )
    assert len(rows) == 2  # append-only: both kept
    assert rows[0].value_per_unit == 64.0  # latest = max(id)
    assert rows[0].fetched_at.tzinfo is not None
    assert rows[1].value_per_unit == 60.0


def test_valuation_source_defaults_to_ebay_sold_median(db):
    p = SealedPurchase(query="pack", cost_per_unit=5.0)
    db.add(p)
    db.commit()
    v = SealedValuation(purchase_id=p.id, value_per_unit=6.0, comp_count=3)
    db.add(v)
    db.commit()
    assert db.get(SealedValuation, v.id).source == "ebay_sold_median"