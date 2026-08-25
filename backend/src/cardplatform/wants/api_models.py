"""Pydantic v2 wire models for the want list / hunt list (roadmap row 24).

Mirror the frozen dataclasses in `wants/service.py` for the API layer. Kept in
their own module (NOT imported from cardplatform.api) to avoid a circular import:
the router imports these, the service imports nothing from the API.

Honest fields on every slot: `market_price` is the resolved market reference or
`null` (a missing price is null, never a fabricated `$0`); `target_price` is the
user's willingness-to-pay or `null` (honest "no target"); `deal_gap` is
`target_price - market_price` or `null` when either is missing; `within_target`
is True only when both are present and the market is at or below the target.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WantItemOut(BaseModel):
    """One want-list slot joined to its catalog row + market reference."""

    model_config = ConfigDict(from_attributes=True)

    card_id: str
    variant: str
    target_price: float | None
    note: str | None
    added_at: datetime
    card_name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    image_large: str | None
    market_price: float | None
    market_source: str | None
    market_source_updated_at: str | None
    deal_gap: float | None
    within_target: bool | None


class WantListResponse(BaseModel):
    """Response for GET /wants."""

    items: list[WantItemOut]


class WantAddIn(BaseModel):
    """Body for POST /wants/items. `variant` defaults to 'normal'."""

    card_id: str
    variant: str = "normal"
    target_price: float | None = None
    note: str | None = None


class WantPatchIn(BaseModel):
    """Body for PATCH /wants/items/{card_id}/{variant}. Either field optional;
    `target_price: null` and `note: null` clear them. Omitted fields are left
    intact (Pydantic leaves them unset, the service distinguishes unset vs
    None via a sentinel)."""

    target_price: float | None = None
    note: str | None = None