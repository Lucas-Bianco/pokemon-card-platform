"""Pydantic models for the vault import route (roadmap row 30).

Kept in its own module to mirror the binder / wants / sold packages and keep
api.py's import surface flat. The alias used in api.py is `collection_import_models`
to avoid colliding with anything else named `collection_models`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ImportSkipOut(BaseModel):
    """One skipped row — an honest reason it was not imported."""

    row_number: int
    card_id: str | None
    reason: str


class ImportReportOut(BaseModel):
    """The outcome of an import. `total` input rows → `added` holdings + the
    rest `skipped` with reasons. Honest: skipped rows are listed, never
    silently dropped or coerced."""

    model_config = ConfigDict(from_attributes=True)

    total: int
    added: int
    skipped: list[ImportSkipOut]
    caveat: str