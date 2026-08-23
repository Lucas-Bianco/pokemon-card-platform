"""Sealed-product listings provider interface (Phase 05c).

Query-keyed sibling of `prices/listings_provider.py`. Sealed products (booster boxes, ETBs,
collection boxes, packs) are not cards — they have no `card_id`/`variant`, so they carry the
free-text `query` the user searched for. A provider that cannot reach its source, has no
API key configured, or receives an unparseable response returns [] — it NEVER raises (the
same discipline as ListingsProvider / GradedPriceProvider). Callers treat [] as "no
listings/sold comps for this query", not an error.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SealedListing:
    """One active marketplace listing for a sealed-product query.

    Mirrors `ListingQuote` but query-keyed (no card_id/variant). `price`/`currency` are the
    asking/bid price; fields the source omits are None, never fabricated. `listing_type` is
    "fixed_price" or "auction"; `auction_end_at` is the tz-aware UTC auction end or None.
    `source` is REQUIRED (no default). `source_updated_at` is None (Finding API exposes no
    per-listing stamp).
    """
    query: str
    listing_id: str
    source: str
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    listing_type: str | None = None
    auction_end_at: datetime | None = None
    url: str | None = None
    condition: str | None = None
    source_updated_at: str | None = None
    seller: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class SealedSoldComp:
    """One recently-sold eBay listing for a sealed-product query — sale evidence.

    Mirrors `SoldComp` but query-keyed. Distinct from SealedListing: a sold comp carries
    `sold_at` (sale close) and no listing_type/auction_end_at. NEVER persisted (on-demand
    evidence only); `source="ebay"`. Only confirmed sales (sellingState=="EndedWithSales").
    """
    query: str
    listing_id: str
    price: float
    title: str | None = None
    currency: str | None = None
    url: str | None = None
    condition: str | None = None
    sold_at: datetime | None = None
    source: str = "ebay"


class SealedListingsProvider(Protocol):
    """A source of active listings + sold comps for a sealed-product free-text query.

    Method names use the `_by_query` suffix so the concrete eBay adapter (which already has
    card-keyed `fetch_listings`/`fetch_sold_listings`) can implement both contracts without
    a name collision. A future TCGplayer sealed adapter implements the same methods.
    """
    name: str

    def fetch_listings_by_query(self, query: str) -> list[SealedListing]:
        """Active listings for the query. Returns [] on failure — never raises."""
        ...

    def fetch_sold_listings_by_query(self, query: str, limit: int = 3) -> list[SealedSoldComp]:
        """Up to `limit` recently-sold listings (sale evidence). [] on failure — never raises."""
        ...
