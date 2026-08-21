"""Pydantic wire models for the set-completion API (Phase 06).

Mirrors the sealed/deals api_models idiom: Pydantic v2 with
``ConfigDict(from_attributes=True)`` so the service's frozen dataclasses serialise
directly. Every nullable field surfaces as None — an unpriced missing card is never a
fabricated $0.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SetProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    owned: int
    checklist_size: int
    pct_complete: float


class ChecklistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    card_id: str
    name: str
    number: str
    rarity: str | None
    image_small: str | None
    owned: bool
    market: float | None
    source: str | None
    source_updated_at: str | None


class CompletionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owned: int
    checklist_size: int
    missing: int
    pct_complete: float
    est_cost_to_complete: float | None
    unpriced_missing: int


class SetCompletionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    cards: list[ChecklistEntryOut]
    summary: CompletionSummaryOut