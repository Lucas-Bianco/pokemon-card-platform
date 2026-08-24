"""Pydantic v2 wire models for the trade-up simulator (roadmap row 19).

Mirror the frozen dataclasses in `tradeup/service.py` for the API layer. Kept in
their own module (NOT imported from cardplatform.api) to avoid a circular import:
the router imports these, the service imports nothing from the API.

`from_attributes=True` lets `TradeUpAssessmentOut.model_validate(assessment)` map
the nested frozen dataclass `TradeUpLeg` -> `TradeUpLegOut` recursively.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TradeUpLegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    gross: float | None
    fee: float | None
    net: float | None
    source: str | None
    source_updated_at: str | None
    evidence_count: int | None
    note: str


class TradeUpAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    card_id: str
    variant: str
    grader: str
    target_grade: float
    raw_leg: TradeUpLegOut
    grade_leg: TradeUpLegOut
    market_reference: float | None
    market_reference_source: str | None
    market_reference_source_updated_at: str | None
    recommendation: str | None
    recommendation_note: str
    centering_cap: int | None
    centering_blocks_grading: bool
    caveats: list[str]