"""Pydantic wire models for the sold-comps evidence API (Phase 05b).

Sold comps are recent eBay *sold* listings shown as evidence backing the raw
market price. They are NOT persisted (on-demand fetch only), so these models
serialise the EbayListingsProvider.SoldComp dataclass directly. Honest flags:
`sold_comps_unavailable` is True when no listings_api_key is configured (no
provider); `sold_comps_empty` is True when a key IS set but eBay returned no
sold comps. `sold_at` is the sale close (tz-aware ISO).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SoldCompOut(BaseModel):
    """One recently-sold eBay listing (sale evidence)."""

    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    price: float
    currency: str | None
    url: str | None
    condition: str | None
    sold_at: datetime | None
    source: str


class SoldCompsResponse(BaseModel):
    """Response for GET /cards/{id}/sold-comps."""

    card_id: str
    variant: str
    sold_comps: list[SoldCompOut]
    sold_comps_unavailable: bool
    sold_comps_empty: bool