"""Pydantic wire models for the Phase 05c sealed-deals API.

Mirrors `deals/api_models.py`: Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`
so the engine's dataclasses serialise directly. Every nullable field surfaces as None — a
missing edge input (no sold comps) is never a fabricated $0.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
