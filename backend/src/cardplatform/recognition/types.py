"""Shared vocabulary for the recognition pipeline.

These are the only types that cross module boundaries, so the visual matcher, the OCR
reader, and the fusion layer can each be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["confident", "ambiguous", "not_found"]


@dataclass(frozen=True)
class Candidate:
    """One possible card identity, scored by visual similarity."""

    card_id: str
    visual_score: float


@dataclass(frozen=True)
class OcrReading:
    """What OCR could read off the rectified card.

    Every field is optional: glare, blur, and angle routinely defeat OCR, and the
    fusion layer is expected to cope with a completely empty reading.
    """

    collector_number: str | None = None
    printed_total: str | None = None
    name_text: str | None = None
    raw_regions: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class RecognitionResult:
    """The pipeline's decision, always with calibrated uncertainty attached.

    `status` is the field callers should branch on:
      confident  -> card_id is trustworthy, auto-confirm
      ambiguous  -> show `candidates` and let the user pick
      not_found  -> nothing plausible; card_id is None
    """

    card_id: str | None
    confidence: float
    status: Status
    candidates: tuple[Candidate, ...]
    ocr: OcrReading
    visual_margin: float
