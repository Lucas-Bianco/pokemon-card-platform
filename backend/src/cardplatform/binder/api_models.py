"""Pydantic v2 wire models for the shareable binder (roadmap row 21).

Mirror the frozen dataclasses in `binder/service.py` for the API layer. Kept in
their own module (NOT imported from cardplatform.api) to avoid a circular import:
the router imports these, the service imports nothing from the API.

Honest flags on every slot: `proven_sale` is the whole object or `null` (a missing
sale is null, never a fabricated `$0`); `proven_sale_unavailable` is True when no
eBay key is configured (so the UI says "set a key" not "no sales"); `proven_sale_empty`
is True when a key IS set but eBay returned no comps for this card.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProvenSaleOut(BaseModel):
    """The single most-recent proven eBay sale backing a binder slot."""

    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    price: float
    currency: str | None
    url: str | None
    condition: str | None
    sold_at: datetime | None
    source: str


class BinderItemOut(BaseModel):
    """One binder slot joined to its catalog row + proven sale."""

    model_config = ConfigDict(from_attributes=True)

    card_id: str
    variant: str
    sort_order: int
    note: str | None
    added_at: datetime
    card_name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    image_large: str | None
    proven_sale: ProvenSaleOut | None
    proven_sale_unavailable: bool
    proven_sale_empty: bool


class BinderListResponse(BaseModel):
    """Response for GET /binder."""

    items: list[BinderItemOut]


class BinderAddIn(BaseModel):
    """Body for POST /binder/items. `variant` defaults to 'normal'."""

    card_id: str
    variant: str = "normal"
    note: str | None = None


class BinderKeyIn(BaseModel):
    """One (card_id, variant) slot reference used by the reorder endpoint."""

    card_id: str
    variant: str = "normal"


class BinderReorderIn(BaseModel):
    """Body for POST /binder/reorder — the desired full or partial slot order."""

    items: list[BinderKeyIn]


class BinderNoteIn(BaseModel):
    """Body for PATCH /binder/items/{card_id}/{variant}. `note` null clears it."""

    note: str | None = None