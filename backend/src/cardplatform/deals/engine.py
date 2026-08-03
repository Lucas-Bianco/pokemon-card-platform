"""DealEngine — rip-vs-flip evaluation of active listings (Phase 05).

READ-ONLY. Computes per-listing rip/flip edges on demand from the latest
immutable snapshots via the three never-ad-hoc services (PriceService,
GradedPriceService, ListingsService). Writes nothing — deals are derived from
the newest snapshots each call, so they never go stale in storage and the
sacred-snapshot rule holds. Missing inputs null the edge they feed — never a
fabricated $0, never a fake profit.

rip_edge        = raw_market.price − listing.price
flip_edge_to_9  = psa9.market  − listing.price − grading_fee
flip_edge_to_10 = psa10.market − listing.price − grading_fee
deal_score      = max(rip_edge or 0, flip_edge_to_10 or 0)   # ranking; nulls last

A listing is `is_rip` iff rip_edge >= deal_rip_min_abs AND
rip_edge >= deal_rip_min_pct * raw_market.price. A listing is `is_flip` iff
flip_edge_to_10 >= deal_flip_min_abs. Edges are indicative leads — eBay
keyword listings carry seller-mislabel noise; the UI says "investigate before
buying". This engine never decides "buy" — it surfaces candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.graded_service import GradedPriceService
from cardplatform.prices.listings_service import ListingsService
from cardplatform.prices.service import PriceService


@dataclass(frozen=True)
class _PricePoint:
    price: float
    source: str
    source_updated_at: str


@dataclass(frozen=True)
class _Thresholds:
    deal_rip_min_abs: float
    deal_rip_min_pct: float
    deal_flip_min_abs: float


@dataclass(frozen=True)
class DealAssessment:
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: object | None  # datetime | None
    fetched_at: object  # datetime
    raw_market: _PricePoint | None
    rip_edge: float | None
    psa9_comp: _PricePoint | None
    psa10_comp: _PricePoint | None
    flip_edge_to_9: float | None
    flip_edge_to_10: float | None
    grading_fee: float
    deal_score: float | None
    is_rip: bool
    is_flip: bool
    thresholds: _Thresholds


class DealEngine:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        price_service: PriceService | None = None,
        graded_service: GradedPriceService | None = None,
        listings_service: ListingsService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or default_settings
        self.price_service = price_service or PriceService(session)
        self.graded_service = graded_service or GradedPriceService(session)
        self.listings_service = listings_service or ListingsService(session)

    def assess(self, card_id: str, variant: str) -> list[DealAssessment]:
        """Ranked deals for one (card_id, variant). Empty list if no listings.
        Never raises — missing service inputs surface as honest null edges."""
        raw = self.price_service.latest_price(card_id, variant)
        raw_point = (
            _PricePoint(raw.market, raw.source, raw.source_updated_at)
            if raw is not None and raw.market is not None
            else None
        )
        psa9 = self.graded_service.latest_graded(card_id, variant, 9.0, "PSA")
        psa9_point = (
            _PricePoint(psa9.market, psa9.source, psa9.source_updated_at)
            if psa9 is not None and psa9.market is not None
            else None
        )
        psa10 = self.graded_service.latest_graded(card_id, variant, 10.0, "PSA")
        psa10_point = (
            _PricePoint(psa10.market, psa10.source, psa10.source_updated_at)
            if psa10 is not None and psa10.market is not None
            else None
        )
        fee = self.settings.grading_fee
        th = _Thresholds(
            self.settings.deal_rip_min_abs,
            self.settings.deal_rip_min_pct,
            self.settings.deal_flip_min_abs,
        )

        listings = self.listings_service.latest_listings(card_id, variant)
        assessments: list[DealAssessment] = []
        for row in listings:
            price = row.price
            rip_edge = (
                raw_point.price - price
                if raw_point is not None and price is not None
                else None
            )
            flip9 = (
                psa9_point.price - price - fee
                if psa9_point is not None and price is not None
                else None
            )
            flip10 = (
                psa10_point.price - price - fee
                if psa10_point is not None and price is not None
                else None
            )
            is_rip = (
                rip_edge is not None
                and rip_edge >= th.deal_rip_min_abs
                and rip_edge >= th.deal_rip_min_pct * raw_point.price
            )
            is_flip = flip10 is not None and flip10 >= th.deal_flip_min_abs
            score = (
                max(rip_edge or 0.0, flip10 or 0.0)
                if (rip_edge is not None or flip10 is not None)
                else None
            )
            assessments.append(
                DealAssessment(
                    listing_id=row.listing_id,
                    title=row.title,
                    listing_price=price,
                    currency=row.currency,
                    url=row.url,
                    condition=row.condition,
                    listing_type=row.listing_type,
                    auction_end_at=row.auction_end_at,
                    fetched_at=row.fetched_at,
                    raw_market=raw_point,
                    rip_edge=rip_edge,
                    psa9_comp=psa9_point,
                    psa10_comp=psa10_point,
                    flip_edge_to_9=flip9,
                    flip_edge_to_10=flip10,
                    grading_fee=fee,
                    deal_score=score,
                    is_rip=is_rip,
                    is_flip=is_flip,
                    thresholds=th,
                )
            )

        # deal_score desc, nulls last.
        assessments.sort(key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0)))
        return assessments