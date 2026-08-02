"""Graded-price provider interface.

Mirrors `provider.py`'s PriceProvider protocol: every graded-price source
(PSA/CGC/BGS sold comps) implements this protocol so a replacement can be
added without touching callers. A provider that cannot reach its source, has
no API key configured, or receives an unparseable response returns [] — it
NEVER raises. Callers (GradedPriceService, the CLI) treat [] as "graded prices
unavailable for this card", not as an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GradedPriceQuote:
    """One graded-price observation for one (card, grader, grade, variant) tuple.

    Mirrors PriceQuote's shape plus grader/grade. low/mid/high/market are the
    source's price points for that exact grade; any the source does not
    publish are None rather than fabricated. source_updated_at is the source's
    own freshness stamp (free text), or None when the source omits one — the
    service normalizes None to the "" dedupe sentinel (see GradedPriceSnapshot).
    """

    card_id: str
    grader: str
    grade: float
    variant: str
    low: float | None = None
    mid: float | None = None
    high: float | None = None
    market: float | None = None
    source: str = ""
    source_updated_at: str | None = None


class GradedPriceProvider(Protocol):
    name: str

    def fetch_graded(self, card_id: str) -> list[GradedPriceQuote]:
        """Return every available graded quote for a card. Returns [] on failure — never raises."""
        ...