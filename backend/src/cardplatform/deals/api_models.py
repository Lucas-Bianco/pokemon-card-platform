"""Pydantic wire models for the Phase 05 deals API.

Mirrors the rest of api.py: Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`
so the DealEngine's dataclass assessments can serialise directly. Every nullable
field surfaces as None — a missing edge input (no raw market, no graded comp) is
never a fabricated $0. The engine's internal `_PricePoint` / `_Thresholds`
dataclasses are mapped here to flat nested objects the frontend can read.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PricePointOut(BaseModel):
    """One market price the engine compared the listing against (raw / psa9 / psa10).

    `source` and `source_updated_at` travel with every figure so the UI can say
    where a number came from and how old it is, instead of implying everything is
    current — the same convention as `PriceOut` and `GradingUpsideTierOut`.
    """

    price: float
    source: str
    source_updated_at: str


class ThresholdsOut(BaseModel):
    """The deal thresholds the engine applied for this assessment, echoed in the
    response so the frontend can label why a listing was flagged (or not)."""

    deal_rip_min_abs: float
    deal_rip_min_pct: float
    deal_flip_min_abs: float


class DealAssessmentOut(BaseModel):
    """One ranked listing with its rip/flip edges and flags.

    `rip_edge` / `flip_edge_to_9` / `flip_edge_to_10` are null when the
    corresponding market input is missing — never a fabricated $0. `raw_market`
    / `psa9_comp` / `psa10_comp` are null when no snapshot exists. `is_rip` /
    `is_flip` are honest booleans against the thresholds; a missing edge is
    never a deal.
    """

    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    fetched_at: datetime
    raw_market: PricePointOut | None
    rip_edge: float | None
    psa9_comp: PricePointOut | None
    psa10_comp: PricePointOut | None
    flip_edge_to_9: float | None
    flip_edge_to_10: float | None
    grading_fee: float
    deal_score: float | None
    is_rip: bool
    is_flip: bool


class DealsResponse(BaseModel):
    """Per-card or cross-card deal feed response.

    `listings_unavailable` is True when no `listings_api_key` is configured
    (honest — no provider configured, never fake listings). `listings_empty`
    is True when a key IS set but no listings exist (the source was queried,
    just empty). For the cross-card feed, `card_id` and `variant` are null and
    the flags merge across all assessed cards (unavailable if NO card had a
    key; empty if every card had a key but none had listings). `thresholds`
    echoes the settings the engine applied.
    """

    card_id: str | None = None
    variant: str | None = None
    listings_unavailable: bool
    listings_empty: bool
    deals: list[DealAssessmentOut]
    thresholds: ThresholdsOut