"""Pydantic v2 wire models for the sold-lots ledger (roadmap row 29).

Mirror the frozen dataclasses in `sold/service.py` for the API layer. Kept in
their own module (NOT imported from cardplatform.api) to avoid a circular
import: the router imports these, the service imports nothing from the API.

Honest fields on every lot: `proceeds` is always known (a sale has a price);
`cost_basis` and `realized` are `null` when no cost basis was recorded at sale
time — never a fabricated `$0`. The summary's `total_realized` is over the
cost-known subset only; `total_proceeds` sums all sales.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SoldLotOut(BaseModel):
    """One sold lot joined to its catalog row + derived money fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    card_id: str
    variant: str
    quantity: int
    sale_price: float
    sale_fee: float | None
    acquired_price: float | None
    sold_at: datetime
    source: str | None
    notes: str | None

    card_name: str
    set_id: str
    set_name: str
    number: str

    proceeds: float
    cost_basis: float | None
    realized: float | None


class SoldListResponse(BaseModel):
    """Response for GET /sold-lots."""

    items: list[SoldLotOut]


class SoldAddIn(BaseModel):
    """Body for POST /sold-lots. `variant` defaults to 'normal'; `quantity`
    defaults to 1. `sale_price` is required (a sale has a price).
    `acquired_price` is the per-unit cost basis snapshotted at sale time
    (nullable honest); `sold_at` defaults to now on the server."""

    card_id: str
    variant: str = "normal"
    quantity: int = 1
    sale_price: float
    sale_fee: float | None = None
    acquired_price: float | None = None
    sold_at: datetime | None = None
    source: str | None = None
    notes: str | None = None


class SoldSummaryOut(BaseModel):
    """Aggregate over the sold-lots ledger."""

    model_config = ConfigDict(from_attributes=True)

    lot_count: int
    lots_with_cost: int
    lots_without_cost: int
    total_proceeds: float
    total_cost_basis: float
    total_realized: float
    winners: int
    losers: int
    caveat: str