"""Price provider interface.

pokemontcg.io joined Scrydex in 2026 and its long-term free availability is uncertain.
Every price source implements this protocol so a replacement can be added without
touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PriceQuote:
    card_id: str
    source: str
    variant: str
    low: float | None = None
    mid: float | None = None
    high: float | None = None
    market: float | None = None
    source_updated_at: str | None = None


class PriceProvider(Protocol):
    name: str

    def fetch(self, card_id: str) -> list[PriceQuote]:
        """Return every available quote for a card. Returns [] on failure — never raises."""
        ...
