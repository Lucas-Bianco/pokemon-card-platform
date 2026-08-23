"""Pydantic v2 wire models for the shop-assessor (Phase E).

Mirror the frozen dataclasses in `shop/assess.py` for the API layer. These live in
their own module (NOT imported from cardplatform.api) to avoid a circular import:
the API router imports these, and the assessor imports nothing from the API.

`from_attributes=True` lets `ShopAssessmentOut.model_validate(shop_assessment)`
map the nested frozen dataclasses recursively — ConsistencyResult -> ConsistencyOut,
ChecklistItem -> ChecklistItemOut, ShopAuthenticity -> AuthenticityOut, ShopListing
-> ShopListingOut, ShopMatch -> ShopMatchOut, ShopDeal -> ShopDealOut.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConsistencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    printed_number: str | None
    catalog_number: str | None
    card_id: str | None
    card_name: str | None
    match: str
    note: str


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    what_to_check: str
    caveat: str
    applies: bool


class AuthenticityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    caveat: str
    consistency: ConsistencyOut
    checklist: list[ChecklistItemOut]


class ShopListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: str
    title: str | None
    price: float | None
    currency: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    seller: str | None
    image_url: str | None
    url: str | None
    source: str = "ebay"


class ShopMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    confidence: str
    card_id: str | None = None
    card_name: str | None = None
    card_number: str | None = None
    card_rarity: str | None = None
    set_name: str | None = None
    sealed_slug: str | None = None
    sealed_name: str | None = None


class ShopDealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    market: float | None
    market_source: str | None
    market_source_updated_at: str | None
    sold_comps_count: int
    edge: float | None
    is_deal: bool
    min_abs: float
    min_pct: float
    market_unavailable: bool
    market_empty: bool


class ShopAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    item_id: str | None
    listing_unavailable: bool
    listing_not_found: bool
    listing: ShopListingOut | None
    match: ShopMatchOut
    deal: ShopDealOut | None
    authenticity: AuthenticityOut | None
    caveat: str