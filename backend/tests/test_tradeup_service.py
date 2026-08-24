"""T5: TradeUpService — the honest exit-strategy simulator (roadmap row 19).

Pins the honesty contract at the service boundary (the HTTP test pins the wire
shape separately):

  * The raw leg is the *median of proven eBay sold-comps*, net of the selling
    fee — never a listed ask, never $0. No comps -> an honest None leg + a
    reason, never a fabricated number.
  * The grade leg is the graded market, net of grading fee + selling fee. It
    ASSUMES the card achieves the target grade; a measured centering cap below
    the target flags that grade as not reachable (centering_blocks_grading=True)
    but the figure is still reported + caveated, never silently dropped.
  * `market_reference` is a listed ask shown for context — it is NOT the sell
    price and never feeds the recommendation.
  * The recommendation is *descriptive* of which net is higher (or the only
    estimable leg), never a forecast. Two None legs -> recommendation None.
  * The service is read-only and never raises: a None provider / empty comps /
    missing graded price all degrade to honest Nones.

Snapshots are seeded directly (no network); a tiny stub sold-comps provider
stands in for EbayListingsProvider so the median math is deterministic.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, GradedPriceSnapshot, PriceSnapshot
from cardplatform.prices.listings_provider import SoldComp
from cardplatform.tradeup.service import TradeUpService

# Defaults mirrored from config so the math is explicit in the assertions.
DEFAULT_SELLING_FEE = 0.13
DEFAULT_GRADING_FEE = 25.0


class StubSoldComps:
    """Tiny stand-in for EbayListingsProvider.fetch_sold_listings. Returns a
    fixed list per (card_id, variant) and records calls so the limit is
    assertable. Never touches the network."""

    def __init__(self, comps_by_key: dict[tuple[str, str], list[SoldComp]] | None = None):
        self.comps_by_key = comps_by_key or {}
        self.calls: list[tuple[str, str, int]] = []

    def fetch_sold_listings(self, card_id: str, variant: str, limit: int = 3):
        self.calls.append((card_id, variant, limit))
        return list(self.comps_by_key.get((card_id, variant), []))


def _comp(price: float, card_id="base1-4", variant="holofoil") -> SoldComp:
    return SoldComp(card_id=card_id, variant=variant, listing_id=f"l{price}",
                    price=price, title="Charizard", currency="USD")


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def _raw(db, variant="holofoil", market=120.0, source="tcgplayer",
         source_updated_at="2026/07/29"):
    db.add(PriceSnapshot(
        card_id="base1-4", source=source, variant=variant, market=market,
        source_updated_at=source_updated_at,
    ))
    db.commit()


def _graded(db, grade, variant="holofoil", market=1200.0, grader="PSA",
            source="pkmnprices", source_updated_at="2026/07/28"):
    db.add(GradedPriceSnapshot(
        card_id="base1-4", grader=grader, grade=grade, variant=variant,
        market=market, source=source, source_updated_at=source_updated_at,
    ))
    db.commit()


def _service(seeded, comps=None, settings=None, graded_service=None):
    return TradeUpService(
        seeded, settings=settings, sold_comps_provider=StubSoldComps(comps or {}),
        graded_service=graded_service,
    )


# --- Raw leg: median of proven sales, net of selling fee --------------------

def test_raw_leg_is_median_of_sold_comps_net_of_selling_fee(seeded):
    _raw(seeded, market=120.0)  # market reference only — must NOT feed the raw leg
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [
        _comp(118.0), _comp(121.0), _comp(119.0)
    ]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    # Median of [118, 121, 119] == 119.0; net of 13% selling fee.
    assert a.raw_leg.gross == 119.0
    assert a.raw_leg.fee == pytest.approx(119.0 * DEFAULT_SELLING_FEE)
    assert a.raw_leg.net == pytest.approx(119.0 * (1 - DEFAULT_SELLING_FEE))
    assert a.raw_leg.source == "ebay_sold_median"
    assert a.raw_leg.evidence_count == 3
    assert a.raw_leg.note  # non-empty provenance note


def test_raw_leg_none_when_no_sold_comps(seeded):
    """No comps -> honest None leg with a reason, never $0."""
    _graded(seeded, grade=10.0, market=1200.0)
    svc = _service(seeded, comps={})  # no comps seeded

    a = svc.assess("base1-4", "holofoil")

    assert a.raw_leg.gross is None
    assert a.raw_leg.fee is None
    assert a.raw_leg.net is None
    assert a.raw_leg.evidence_count == 0
    assert a.raw_leg.note  # the honest reason


def test_raw_leg_median_handles_even_count(seeded):
    """Even number of comps -> median is the average of the two middle values."""
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [
        _comp(100.0), _comp(110.0), _comp(130.0), _comp(140.0)
    ]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    # Median of [100,110,130,140] == (110+130)/2 == 120.0
    assert a.raw_leg.gross == 120.0
    assert a.raw_leg.evidence_count == 4


def test_raw_leg_ignores_comps_with_none_price(seeded):
    """A malformed comp with price=None must not poison the median."""
    _graded(seeded, grade=10.0, market=1200.0)
    bad = replace(_comp(100.0), price=None)  # type: ignore[arg-type]
    comps = {("base1-4", "holofoil"): [bad, _comp(120.0), _comp(130.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    # Only the two real comps count; median of [120,130] == 125.0
    assert a.raw_leg.gross == 125.0
    assert a.raw_leg.evidence_count == 2


# --- Grade leg: graded market net of grading + selling fee ------------------

def test_grade_leg_is_graded_market_net_of_both_fees(seeded):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0)

    # gross 1200; fee = grading_fee + 13% of gross; net = gross - fee.
    assert a.grade_leg.gross == 1200.0
    assert a.grade_leg.fee == pytest.approx(DEFAULT_GRADING_FEE + 1200.0 * DEFAULT_SELLING_FEE)
    assert a.grade_leg.net == pytest.approx(
        1200.0 - DEFAULT_GRADING_FEE - 1200.0 * DEFAULT_SELLING_FEE
    )
    assert a.grade_leg.source == "pkmnprices"
    assert a.grade_leg.source_updated_at == "2026/07/28"
    assert a.grade_leg.evidence_count is None  # single provider quote, not a cluster


def test_grade_leg_none_when_no_graded_price(seeded):
    _raw(seeded, market=120.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0)

    assert a.grade_leg.gross is None
    assert a.grade_leg.net is None
    assert a.grade_leg.note  # the honest reason


def test_grade_uses_target_grade_and_grader(seeded):
    """Asking for PSA 9 must pull the PSA-9 graded snapshot, not PSA 10."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=9.0, market=350.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", grader="PSA", target_grade=9.0)

    assert a.grade_leg.gross == 350.0
    assert a.target_grade == 9.0
    assert a.grader == "PSA"


# --- Centering cap ----------------------------------------------------------

def test_centering_cap_below_target_blocks_grading(seeded):
    """A measured centering cap (8) below the target grade (10) flags the grade
    leg as not reachable. The graded figure is still reported (the market
    exists) but centering_blocks_grading=True and the note says so."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0, centering_cap=8)

    assert a.centering_cap == 8
    assert a.centering_blocks_grading is True
    # Figure still reported, never silently dropped:
    assert a.grade_leg.gross == 1200.0
    assert "not reachable" in a.grade_leg.note or "not a real option" in a.grade_leg.note


def test_centering_cap_at_target_does_not_block(seeded):
    """centering_cap == target_grade (10 == 10) does NOT block — only strictly
    below blocks."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0, centering_cap=10)

    assert a.centering_blocks_grading is False


def test_centering_unmeasured_adds_caveat(seeded):
    """No centering_cap supplied -> a caveat says centering is unmeasured."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.centering_cap is None
    assert any("Centering unmeasured" in c for c in a.caveats)


# --- Market reference (an ask, NOT the sell price) --------------------------

def test_market_reference_is_listed_ask_for_context(seeded):
    """market_reference mirrors latest_price (a listed ask); it must NOT feed
    the raw leg (which is proven-sales median) and must NOT be $0 when present."""
    _raw(seeded, market=300.0)  # the ask — deliberately different from the sales
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.market_reference == 300.0
    assert a.market_reference_source == "tcgplayer"
    assert a.market_reference_source_updated_at == "2026/07/29"
    # And the raw leg is the proven median, NOT the ask:
    assert a.raw_leg.gross == 119.0


def test_market_reference_none_when_no_raw_snapshot(seeded):
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.market_reference is None
    assert a.market_reference_source is None


# --- Recommendation: descriptive, never a forecast --------------------------

def test_recommendation_grade_when_grade_nets_more(seeded):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}  # raw net ~103
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.recommendation == "grade"
    assert a.recommendation_note  # descriptive delta


def test_recommendation_sell_raw_when_raw_nets_more(seeded):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=40.0)  # tiny graded market
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}  # raw net ~103 > grade net
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.recommendation == "sell_raw"


def test_recommendation_none_when_both_legs_unestimable(seeded):
    """No comps and no graded price -> neither leg estimable -> None."""
    _raw(seeded, market=120.0)  # ask exists but neither sell leg does
    svc = _service(seeded, comps={})

    a = svc.assess("base1-4", "holofoil")

    assert a.raw_leg.net is None
    assert a.grade_leg.net is None
    assert a.recommendation is None
    assert a.recommendation_note  # the honest reason


def test_recommendation_sell_raw_when_only_raw_estimable(seeded):
    _raw(seeded, market=120.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)  # no graded price

    a = svc.assess("base1-4", "holofoil")

    assert a.recommendation == "sell_raw"


def test_recommendation_grade_when_only_grade_estimable(seeded):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    svc = _service(seeded, comps={})  # no comps

    a = svc.assess("base1-4", "holofoil")

    assert a.recommendation == "grade"


def test_centering_block_forces_sell_raw_when_raw_estimable(seeded):
    """Centering rules out grading -> sell_raw is the only real option, even if
    the (unreachable) graded net would have been higher."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=10_000.0)  # huge but unreachable
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0, centering_cap=8)

    assert a.centering_blocks_grading is True
    assert a.recommendation == "sell_raw"


def test_centering_block_and_no_comps_yields_none(seeded):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    svc = _service(seeded, comps={})  # no comps, centering blocks grading

    a = svc.assess("base1-4", "holofoil", target_grade=10.0, centering_cap=8)

    assert a.centering_blocks_grading is True
    assert a.recommendation is None


# --- Read-only + never raises + variant scoping -----------------------------

def test_no_provider_yields_empty_comps_not_raise(seeded):
    """A None sold_comps provider (no key configured) -> empty comps, honest
    None raw leg, never an exception."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    svc = TradeUpService(seeded)  # no sold_comps_provider

    a = svc.assess("base1-4", "holofoil")

    assert a.raw_leg.net is None
    assert a.raw_leg.evidence_count == 0
    assert a.grade_leg.gross == 1200.0  # grade leg still works without comps


def test_variant_scopes_graded_and_raw_lookups(seeded):
    """Asking for holofoil must not pull reverseHolofoil snapshots or comps."""
    _raw(seeded, variant="holofoil", market=120.0)
    _raw(seeded, variant="reverseHolofoil", market=20.0)
    _graded(seeded, grade=10.0, variant="holofoil", market=1200.0)
    _graded(seeded, grade=10.0, variant="reverseHolofoil", market=40.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0, variant="holofoil")]}
    svc = _service(seeded, comps=comps)

    a = svc.assess("base1-4", "holofoil")

    assert a.variant == "holofoil"
    assert a.grade_leg.gross == 1200.0  # holofoil graded, not the 40 reverse
    assert a.market_reference == 120.0
    assert a.raw_leg.gross == 119.0


def test_assess_never_writes(seeded):
    """The simulator is read-only: assess must not create any new rows."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)
    comps = {("base1-4", "holofoil"): [_comp(119.0)]}
    svc = _service(seeded, comps=comps)

    from cardplatform.db.models import PriceSnapshot, GradedPriceSnapshot
    before_p = seeded.query(PriceSnapshot).count()
    before_g = seeded.query(GradedPriceSnapshot).count()

    svc.assess("base1-4", "holofoil")

    assert seeded.query(PriceSnapshot).count() == before_p
    assert seeded.query(GradedPriceSnapshot).count() == before_g


# --- Custom settings flow through -------------------------------------------

def test_custom_selling_fee_and_grading_fee_flow_through(seeded, tmp_path):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1000.0)
    comps = {("base1-4", "holofoil"): [_comp(200.0)]}
    custom = Settings(data_dir=tmp_path)
    custom.selling_fee_pct = 0.20
    custom.grading_fee = 50.0
    svc = _service(seeded, comps=comps, settings=custom)

    a = svc.assess("base1-4", "holofoil", target_grade=10.0)

    # raw: 200 net of 20% -> 160
    assert a.raw_leg.net == pytest.approx(200.0 * (1 - 0.20))
    # grade: 1000 net of (50 + 20% of 1000) -> 1000 - 50 - 200 == 750
    assert a.grade_leg.net == pytest.approx(1000.0 - 50.0 - 1000.0 * 0.20)