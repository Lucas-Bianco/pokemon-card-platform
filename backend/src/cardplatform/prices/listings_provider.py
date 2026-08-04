"""Listings (raw marketplace listing) provider interface.

Mirrors `graded_provider.py`'s GradedPriceProvider protocol: every listings
source (eBay, TCGplayer, etc.) implements this protocol so a replacement can be
added without touching callers. A provider that cannot reach its source, has
no API key configured, or receives an unparseable response returns [] — it
NEVER raises. Callers (ListingsService, the CLI, the alert diff loop in T3)
treat [] as "no listings available for this card", not as an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ListingQuote:
    """One marketplace listing observation for one (card, variant) tuple.

    Mirrors GradedPriceQuote's shape but per-listing instead of per-grade-bucket.
    `price`/`currency` are the asking/bid price, and any field the source does
    not publish, are None rather than fabricated. `listing_type` is "fixed_price" or
    "auction". `auction_end_at` is the tz-aware UTC auction end, or None for
    fixed-price listings. `source` is REQUIRED (no default) — matches the
    GradedPriceQuote convention. `source_updated_at` is the source's own
    per-listing freshness stamp (free text), or None when the source omits one —
    the service normalizes None to the "" dedupe sentinel (see
    ListingSnapshot).
    """

    card_id: str
    variant: str
    listing_id: str
    source: str
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    listing_type: str | None = None  # "fixed_price" | "auction"
    auction_end_at: datetime | None = None
    url: str | None = None
    condition: str | None = None
    source_updated_at: str | None = None


@dataclass(frozen=True)
class SoldComp:
    """One recently-sold eBay listing for a (card, variant) — sale evidence.

    Backs the raw market price in the UI ("market $120 because these 3 just
    sold at $118/$121/$119"). Distinct from ListingQuote: a sold comp carries
    `sold_at` (the sale close, from listingInfo.endTime) and no listing_type /
    auction_end_at — completed listings are historical, not active. Sold comps
    are NEVER persisted (on-demand evidence only); `source="ebay"`.
    """

    card_id: str
    variant: str
    listing_id: str
    price: float
    title: str | None = None
    currency: str | None = None
    url: str | None = None
    condition: str | None = None
    sold_at: datetime | None = None
    source: str = "ebay"


class ListingsProvider(Protocol):
    name: str

    def fetch_listings(self, card_id: str, variant: str) -> list[ListingQuote]:
        """Return every available listing quote for a card+variant. Returns []
        on failure — never raises."""
        ...