"""SealedDealEngine — flip-edge evaluation of sealed-product listings (Phase 05c).

READ-ONLY. Computes per-listing flip-edges on demand from a SealedListingsProvider's
active listings + sold comps. Writes nothing — deals are derived fresh each call, so they
never go stale in storage and the sacred-snapshot rule holds. Missing inputs null the edge
they feed — never a fabricated $0, never a fake profit.

sealed_market = median(sold comp prices)            # None if no comps -> all flip_edges null
flip_edge     = sealed_market - listing.price        # None if market or listing.price missing
is_flip       = flip_edge is not None
                and flip_edge >= sealed_flip_min_abs
                and flip_edge >= sealed_flip_min_pct * sealed_market
deal_score    = flip_edge if not None else None      # ranking; nulls last

Edges are indicative leads — eBay keyword search carries seller-mislabel noise; the UI says
"investigate before buying". This engine never decides "buy" — it surfaces candidates. Rip EV
(opening for expected pull value) is deferred: it needs a product-contents master + pull-rate
tables we do not have (same blocked-on-data class as the full Grade predictor).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from cardplatform.config import Settings, settings as default_settings
from cardplatform.sealed.provider import SealedListingsProvider


@dataclass(frozen=True)
class SealedPricePoint:
    """The market reference a listing was compared against (median of recent sold comps).

    `source` + `source_updated_at` travel with the figure so the UI can say where it came
    from — sold comps expose no per-sale source stamp, so `source_updated_at` is None.
    """
    price: float
    source: str
    source_updated_at: str | None


@dataclass(frozen=True)
class SealedThresholds:
    sealed_flip_min_abs: float
    sealed_flip_min_pct: float


@dataclass(frozen=True)
class SealedDealAssessment:
    query: str
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: object | None  # datetime | None
    fetched_at: object  # datetime
    sealed_market: SealedPricePoint | None
    flip_edge: float | None
    deal_score: float | None
    is_flip: bool
    thresholds: SealedThresholds


@dataclass(frozen=True)
class SealedDealResult:
    """The full on-demand assessment for one query: ranked assessments + the counts/flags
    the API needs to render honest empty states (unavailable is derived from settings at
    the API layer; empty is `count == 0` while a key is set)."""
    query: str
    assessments: list[SealedDealAssessment]
    listings_count: int
    comps_count: int
    sealed_market: SealedPricePoint | None
    thresholds: SealedThresholds


def _median(prices: list[float]) -> float | None:
    return statistics.median(prices) if prices else None


class SealedDealEngine:
    def __init__(
        self,
        provider: SealedListingsProvider,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or default_settings

    def assess(self, query: str, limit: int = 20) -> SealedDealResult:
        """Ranked flip-edge deals for one sealed-product query. Never raises — missing
        sold comps surface as a null `sealed_market` (and therefore null flip_edges)."""
        listings = self.provider.fetch_listings_by_query(query)[: max(0, limit)]
        comps = self.provider.fetch_sold_listings_by_query(query, self.settings.sealed_sold_comp_limit)

        comp_prices = [c.price for c in comps if c.price is not None]
        market_price = _median(comp_prices)
        sealed_market = (
            SealedPricePoint(price=market_price, source="ebay", source_updated_at=None)
            if market_price is not None else None
        )

        th = SealedThresholds(
            self.settings.sealed_flip_min_abs,
            self.settings.sealed_flip_min_pct,
        )
        now = datetime.now(timezone.utc)
        assessments: list[SealedDealAssessment] = []
        for row in listings:
            price = row.price
            flip_edge = (
                sealed_market.price - price
                if sealed_market is not None and price is not None
                else None
            )
            is_flip = (
                flip_edge is not None
                and sealed_market is not None
                and flip_edge >= th.sealed_flip_min_abs
                and flip_edge >= th.sealed_flip_min_pct * sealed_market.price
            )
            assessments.append(SealedDealAssessment(
                query=query,
                listing_id=row.listing_id,
                title=row.title,
                listing_price=price,
                currency=row.currency,
                url=row.url,
                condition=row.condition,
                listing_type=row.listing_type,
                auction_end_at=row.auction_end_at,
                fetched_at=now,
                sealed_market=sealed_market,
                flip_edge=flip_edge,
                deal_score=flip_edge,  # sealed has a single edge; null when missing
                is_flip=is_flip,
                thresholds=th,
            ))

        # deal_score desc, nulls last.
        assessments.sort(key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0)))
        return SealedDealResult(
            query=query,
            assessments=assessments,
            listings_count=len(listings),
            comps_count=len(comps),
            sealed_market=sealed_market,
            thresholds=th,
        )
