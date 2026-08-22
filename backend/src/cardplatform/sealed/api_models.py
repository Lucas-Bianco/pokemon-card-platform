"""Pydantic wire models for the Phase 05c sealed-deals API.

Mirrors `deals/api_models.py`: Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`
so the engine's dataclasses serialise directly. Every nullable field surfaces as None — a
missing edge input (no sold comps) is never a fabricated $0.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SealedPricePointOut(BaseModel):
    """The market reference (median of recent sold comps) compared against each listing.

    `source` + `source_updated_at` travel with the figure; sold comps expose no per-sale
    stamp so `source_updated_at` is None.
    """
    model_config = ConfigDict(from_attributes=True)

    price: float
    source: str
    source_updated_at: str | None


class SealedThresholdsOut(BaseModel):
    sealed_flip_min_abs: float
    sealed_flip_min_pct: float


class SealedDealAssessmentOut(BaseModel):
    """One ranked sealed listing with its flip-edge + flag.

    `flip_edge` / `deal_score` are null when `sealed_market` is None (no sold comps) or the
    listing price is missing — never a fabricated $0. `sealed_market` is null when no sold
    comps exist. `is_flip` is an honest boolean against the thresholds; a null edge is never
    a deal.
    """
    model_config = ConfigDict(from_attributes=True)

    query: str
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    fetched_at: datetime
    sealed_market: SealedPricePointOut | None
    flip_edge: float | None
    deal_score: float | None
    is_flip: bool


class SealedDealsResponse(BaseModel):
    """Sealed-product deal feed for one query.

    `listings_unavailable` is True when no `listings_api_key` is configured (sealed reuses
    the eBay listings key — no separate sealed key). `listings_empty` is True when a key IS
    set but no active listings were found. `comps_unavailable` / `comps_empty` mirror that
    for the sold comps that establish `sealed_market`. `sealed_market` is null when no sold
    comps -> every `flip_edge` is null (honest, never $0).
    """
    query: str
    limit: int
    listings_unavailable: bool
    listings_empty: bool
    comps_unavailable: bool
    comps_empty: bool
    sealed_market: SealedPricePointOut | None
    deals: list[SealedDealAssessmentOut]
    thresholds: SealedThresholdsOut


# --------------------------------------------------------------- Phase 05d ledger


class SealedPurchaseIn(BaseModel):
    """Create payload for a logged sealed-product buy. `quantity`/`cost_per_unit` are
    validated server-side too (LedgerService raises ValueError -> 422), but the Pydantic
    bounds give a clean 422 before the service is even constructed."""

    query: str
    product_type: str | None = None
    quantity: int = Field(default=1, ge=1)
    cost_per_unit: float = Field(ge=0)
    source: str | None = None
    listing_url: str | None = None
    notes: str | None = None
    bought_at: datetime | None = None


class SealedPurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime


class SealedLedgerEntryOut(BaseModel):
    """One ledger row — a purchase joined with its latest valuation + read-only profit.
    Nulls are honest (unvalued), never $0. `valued` is the honest boolean for the front-end."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    total_cost: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime
    value_per_unit: float | None
    total_current_value: float | None
    profit: float | None
    profit_pct: float | None
    market_fetched_at: datetime | None
    market_source: str | None
    valued: bool


class SealedLedgerResponse(BaseModel):
    """Full ledger view. `listings_unavailable` is True when no `listings_api_key` is
    configured (the same eBay key sealed reuses) — the front-end shows the honest banner
    instead of fabricated $0 valuations."""

    purchases: list[SealedLedgerEntryOut]
    listings_unavailable: bool


class ValuationRefreshResultOut(BaseModel):
    """Outcome of POST /sealed/ledger/valuate. `skipped_no_key` is True only when the key
    was missing AND nothing was valued (honest diagnostic, not a blanket flag)."""

    model_config = ConfigDict(from_attributes=True)
    valued: int
    skipped_no_comps: int
    skipped_no_key: bool


class SheetsSyncResultOut(BaseModel):
    """Result of a Google Sheets sync push. Defined now (T3) but unused until T7 — the
    sync route is a separate task. `reason` surfaces the honest no-key / no-rows case."""

    synced: bool
    rows: int
    reason: str | None = None


# --------------------------------------------------------- Phase 16 proof of sales


class SealedSoldCompOut(BaseModel):
    """One recently-sold eBay listing for a sealed-product query — proven sale evidence.

    Mirrors `SealedSoldComp` (query-keyed) and `sold_comps_api_models.SoldCompOut`
    (card-keyed) field-for-field. `from_attributes=True` so the provider's frozen
    dataclass serialises directly. On-demand only — never persisted. `source="ebay"`;
    `sold_at` is the sale-close timestamp (the EndedWithSales gate already confirmed it
    is a real transaction, not a listed estimate)."""

    model_config = ConfigDict(from_attributes=True)

    query: str
    listing_id: str
    price: float
    title: str | None = None
    currency: str | None = None
    url: str | None = None
    condition: str | None = None
    sold_at: datetime | None = None
    source: str = "ebay"


class SealedSoldCompsResponse(BaseModel):
    """Proof-of-sales feed for one sealed-product query (roadmap row 16).

    The individual sold-comps behind the median `sealed_market` shown on /sealed/deals —
    actual eBay transactions (date/price/condition/title/link), so the user sees real
    people paid real money, not a retailer's listed estimate. Honest empty flags mirror
    the established `*_unavailable` (no listings_api_key) vs `*_empty` (key set, 0 comps)
    pattern: `sold_comps_unavailable` is True when no key is configured (the front-end
    shows "set a listings key" instead of fabricated $0); `sold_comps_empty` is True when
    a key IS set but eBay returned 0 confirmed sales."""

    query: str
    limit: int
    sold_comps: list[SealedSoldCompOut]
    sold_comps_unavailable: bool
    sold_comps_empty: bool


# --------------------------------------------------------- Phase A sealed catalog


class SealedProductOut(BaseModel):
    """One sealed-product reference-catalog row (Phase A, roadmap row 09).

    `from_attributes=True` so the ORM model serialises directly. `msrp` is nullable —
    many products have no official US MSRP (booster boxes, premiums) and the UI shows
    "no MSRP", never a fabricated `$0`. `print_status` is a best-effort tag
    (`in_print` / `out_of_print` / `unknown`), never a guarantee."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    era: str | None = None
    product_type: str
    msrp: float | None = None
    msrp_currency: str = "USD"
    print_status: str = "unknown"
    source_url: str | None = None
    image_url: str | None = None
    released_at: str | None = None
    source: str = "manual"
    created_at: datetime


class SealedProductsResponse(BaseModel):
    """Catalog browse/search result. `product_type`/`print_status` echo the active
    filters (None when unfiltered) so the UI can reflect its own state. The seed is
    curated + in-repo (a future semi-automated community sync is a documented
    follow-up, never magic auto-update); `count` is the returned page size, not the
    total catalog size."""

    products: list[SealedProductOut]
    count: int
    product_type: str | None = None
    print_status: str | None = None


# --------------------------------------------------------- Phase B scan-to-log


class SealedScanLogIn(BaseModel):
    """Log a sealed-product buy straight from a catalog row, by slug (Phase B).

    The product's name + product_type are looked up server-side from the catalog,
    so the client only sends the slug + the purchase facts. `quantity`/`cost_per_unit`
    carry Pydantic bounds (clean 422 before the service runs); the service re-validates
    and raises ValueError -> 422. Optional fields default to None — honest empty,
    never an empty-string fabrication."""

    slug: str
    quantity: int = Field(default=1, ge=1)
    cost_per_unit: float = Field(ge=0)
    source: str | None = None
    listing_url: str | None = None
    notes: str | None = None
    bought_at: datetime | None = None


# --------------------------------------------------------- Phase C MSRP vs market


class SealedProductMarketOut(BaseModel):
    """One catalog product's curated MSRP compared to its live sold-comps median (Phase C).

    Every nullable figure is None (never 0): `msrp` is None where no official US MSRP
    exists (booster boxes, premiums); `market_median` is None when there are no comps;
    `delta` is None unless BOTH msrp and market_median are real numbers. The honest
    flags mirror /sealed/sold-comps exactly: `unavailable` = no listings_api_key
    configured (the provider returns [] without hitting the network — "we can't tell",
    never a fabricated number); `empty` = key set but 0 confirmed sales ("no recent
    sales"). `market_source` + `market_source_updated_at` travel with the figure so the
    UI can say where it came from; sold comps carry no per-sale stamp, so the latter is
    None."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    msrp: float | None = None
    msrp_currency: str = "USD"
    market_median: float | None = None
    market_source: str | None = None
    market_source_updated_at: str | None = None
    sold_comps_count: int
    delta: float | None = None
    unavailable: bool
    empty: bool
