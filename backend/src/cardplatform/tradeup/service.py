"""Trade-up / sell-now simulator — the honest form of an exit-strategy tool.

For a card you own, compares two exit legs:

  * **Sell raw now** — revenue from *proven* eBay sold-comps (actual
    transactions, `findCompletedItems` with the `EndedWithSales` gate), net of
    an estimated selling fee. The TCGplayer/`latest_price` market figure is
    shown alongside as a *reference* (an ask), never used as the sell price —
    you can only realise what people have actually paid.

  * **Grade then sell** — revenue from the graded-price provider (e.g. PSA 10
    `pkmnprices`), net of the grading fee and the selling fee. Honest about the
    fact that the graded price *assumes the card achieves the target grade*;
    a measured centering cap can rule that out, in which case the grade leg is
    honestly flagged as not reachable from this card.

The verdict is descriptive of two honest figures, never a forecast. Every net
carries its source + staleness; a missing leg is an em dash + a reason, never
a fabricated $0. Providers degrade to `[]`/`None` and never raise.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Protocol

from cardplatform.config import Settings
from cardplatform.prices.graded_service import GradedPriceService
from cardplatform.prices.service import PriceService
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TradeUpLeg:
    """One exit strategy. `gross`/`net` are None when the leg can't be estimated
    honestly — the `note` says why, and the UI shows an em dash, never $0."""

    label: str
    # Gross realisable revenue (proven median for raw, graded market for grade).
    gross: float | None
    # The fee(s) subtracted to reach `net` (selling fee for raw; grading fee +
    # selling fee for grade). None when gross is None.
    fee: float | None
    # What you'd actually pocket. None when there is no honest gross to net.
    net: float | None
    # Where the gross figure came from (e.g. "ebay_sold_median", "pkmnprices"),
    # plus its staleness — a number is never shown without provenance.
    source: str | None
    source_updated_at: str | None
    # How many transactions back the proven median (raw leg only); None for the
    # grade leg (a single provider quote, not a cluster).
    evidence_count: int | None
    # The honest reason a leg is None, or a short descriptor when it is priced.
    note: str


@dataclass(frozen=True)
class TradeUpAssessment:
    card_id: str
    variant: str
    grader: str
    target_grade: float
    raw_leg: TradeUpLeg
    grade_leg: TradeUpLeg
    # The listed market reference (an ask), shown for context — NOT the sell
    # price. You realise proven sales, not asks.
    market_reference: float | None
    market_reference_source: str | None
    market_reference_source_updated_at: str | None
    # One of "sell_raw", "grade", None. Descriptive of which net is higher (or
    # the only estimable leg); never a forecast of what the card will do.
    recommendation: str | None
    recommendation_note: str
    # The measured PSA ceiling the user supplied (from a scan's centering), or
    # None when centering is unmeasured. When it is below the target grade the
    # grade leg is flagged unreachable — "grading only pays if the card can
    # actually reach the grade".
    centering_cap: int | None
    # True when centering rules out the target grade. The grade leg's gross/net
    # are still reported (the graded market exists) but flagged not-reachable.
    centering_blocks_grading: bool
    caveats: list[str] = field(default_factory=list)


class _SoldCompsProvider(Protocol):
    """The slice of `EbayListingsProvider` the simulator needs. Defining it
    locally keeps the service testable with a tiny stub and avoids importing the
    network-bearing provider at module load."""

    def fetch_sold_listings(
        self, card_id: str, variant: str, limit: int = 3
    ) -> list: ...


# How many recent sold comps back the proven median. Tight cluster, like the
# sold-comps panel — a sell-now estimate from a year of stale sales would lie.
_SOLD_COMP_LIMIT = 6


class TradeUpService:
    """Read-only: never writes, never raises. A missing provider/key simply
    yields empty comps and an honest None leg."""

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        sold_comps_provider: _SoldCompsProvider | None = None,
        graded_service: GradedPriceService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.sold_comps = sold_comps_provider
        self.prices = PriceService(session)
        self.graded = graded_service or GradedPriceService(session)

    def assess(
        self,
        card_id: str,
        variant: str,
        *,
        grader: str = "PSA",
        target_grade: float = 10.0,
        centering_cap: int | None = None,
    ) -> TradeUpAssessment:
        fee_pct = self.settings.selling_fee_pct
        grading_fee = self.settings.grading_fee

        # --- Raw leg: proven eBay sold-comps median, net of selling fee ---
        comps = (
            self.sold_comps.fetch_sold_listings(card_id, variant, _SOLD_COMP_LIMIT)
            if self.sold_comps is not None
            else []
        )
        # A comp with no price isn't evidence; the provider guarantees price is
        # set, but guard anyway so a malformed row can't poison the median.
        prices = [c.price for c in comps if c.price is not None]
        if prices:
            raw_gross = statistics.median(prices)
            raw_fee = raw_gross * fee_pct
            raw_net = raw_gross - raw_fee
            raw_leg = TradeUpLeg(
                label="Sell raw now",
                gross=raw_gross,
                fee=raw_fee,
                net=raw_net,
                source="ebay_sold_median",
                source_updated_at=None,  # comps carry per-sale sold_at, not one stamp
                evidence_count=len(prices),
                note=f"Median of {len(prices)} recent eBay sale(s), net of ~{fee_pct:.0%} selling fee.",
            )
        else:
            raw_leg = TradeUpLeg(
                label="Sell raw now",
                gross=None,
                fee=None,
                net=None,
                source=None,
                source_updated_at=None,
                evidence_count=0,
                note="No proven eBay sales found — can't estimate a sell-now price honestly.",
            )

        # --- Grade leg: graded market, net of grading fee + selling fee ---
        centering_blocks = (
            centering_cap is not None and centering_cap < target_grade
        )
        graded_snap = self.graded.latest_graded(card_id, variant, target_grade, grader)
        if graded_snap is not None and graded_snap.market is not None:
            grade_gross = graded_snap.market
            grade_fee = grading_fee + grade_gross * fee_pct
            grade_net = grade_gross - grade_fee
            if centering_blocks:
                grade_note = (
                    f"Graded {grader} {int(target_grade)} market is {grade_gross:.2f}, but the "
                    f"card's centering caps it at ~{grader} {centering_cap} — that grade is not "
                    "reachable from this card, so this leg is not a real option."
                )
            else:
                grade_note = (
                    f"Graded {grader} {int(target_grade)} market, net of ${grading_fee:.2f} grading "
                    f"fee + ~{fee_pct:.0%} selling fee. Assumes the card achieves the grade."
                )
            grade_leg = TradeUpLeg(
                label=f"Grade to {grader} {int(target_grade)}, then sell",
                gross=grade_gross,
                fee=grade_fee,
                net=grade_net,
                source=graded_snap.source,
                source_updated_at=graded_snap.source_updated_at or None,
                evidence_count=None,
                note=grade_note,
            )
        else:
            if centering_blocks:
                grade_note = (
                    f"No graded {grader} {int(target_grade)} price, and centering caps this card "
                    f"below {int(target_grade)} anyway — grading is not a real option here."
                )
            else:
                grade_note = (
                    f"No graded {grader} {int(target_grade)} price available (set a graded-price "
                    "provider key) — the grade leg can't be estimated."
                )
            grade_leg = TradeUpLeg(
                label=f"Grade to {grader} {int(target_grade)}, then sell",
                gross=None,
                fee=None,
                net=None,
                source=None,
                source_updated_at=None,
                evidence_count=None,
                note=grade_note,
            )

        # --- Market reference (an ask) for context, NOT the sell price ---
        snap = self.prices.latest_price(card_id, variant)
        if snap is not None and snap.market is not None:
            market_reference = snap.market
            market_ref_source = snap.source
            market_ref_stamp = snap.source_updated_at or None
        else:
            market_reference = None
            market_ref_source = None
            market_ref_stamp = None

        recommendation, rec_note = self._recommend(
            raw_leg, grade_leg, centering_blocks
        )

        caveats = [
            f"Net figures subtract an estimated ~{fee_pct:.0%} selling fee and the "
            f"${grading_fee:.2f} grading fee where applicable — a planning estimate, "
            "not a quote; the platform's actual fee applies.",
            "Proven sales are recent eBay transactions; the market reference is a listed ask.",
            "Grading outcome is not guaranteed — the graded price assumes the card achieves the target grade.",
        ]
        if centering_cap is None:
            caveats.append(
                "Centering unmeasured — supply a scan's centering cap to rule out "
                "grades this card can't reach."
            )

        return TradeUpAssessment(
            card_id=card_id,
            variant=variant,
            grader=grader,
            target_grade=target_grade,
            raw_leg=raw_leg,
            grade_leg=grade_leg,
            market_reference=market_reference,
            market_reference_source=market_ref_source,
            market_reference_source_updated_at=market_ref_stamp,
            recommendation=recommendation,
            recommendation_note=rec_note,
            centering_cap=centering_cap,
            centering_blocks_grading=centering_blocks,
            caveats=caveats,
        )

    @staticmethod
    def _recommend(
        raw: TradeUpLeg, grade: TradeUpLeg, centering_blocks: bool
    ) -> tuple[str | None, str]:
        raw_n = raw.net
        grade_n = grade.net
        if centering_blocks:
            # Grading is ruled out by centering regardless of its price.
            if raw_n is not None:
                return (
                    "sell_raw",
                    "Centering rules out the target grade, so sell raw is the only "
                    "real option among these two.",
                )
            return (
                None,
                "Centering rules out grading and there are no proven raw sales — "
                "neither leg could be estimated honestly.",
            )
        if raw_n is None and grade_n is None:
            return (
                None,
                "Neither leg could be estimated honestly — no proven sales and no "
                "graded price.",
            )
        if raw_n is None:
            return (
                "grade",
                "Only the grade leg could be estimated (no proven raw sales to "
                "compare against).",
            )
        if grade_n is None:
            return (
                "sell_raw",
                "Only the sell-raw leg could be estimated (no graded price to "
                "compare against).",
            )
        # Both priced — describe which net is higher. Descriptive, not a forecast.
        if grade_n > raw_n:
            delta = grade_n - raw_n
            return (
                "grade",
                f"Grading nets ~${delta:.2f} more than selling raw, before any risk "
                "that the card doesn't achieve the grade.",
            )
        delta = raw_n - grade_n
        return (
            "sell_raw",
            f"Selling raw nets ~${delta:.2f} more than grading — and skips the "
            "risk the card doesn't grade.",
        )