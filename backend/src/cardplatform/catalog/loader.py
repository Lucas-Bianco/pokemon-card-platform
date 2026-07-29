"""Loads the JSON dump into the database. Idempotent: safe to re-run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CardSet


class DumpSource(Protocol):
    def fetch_sets(self) -> list[dict[str, Any]]: ...
    def fetch_cards(self, set_id: str) -> list[dict[str, Any]]: ...


@dataclass
class LoadResult:
    sets_loaded: int = 0
    cards_loaded: int = 0


class CatalogLoader:
    def __init__(self, session: Session, dump: DumpSource) -> None:
        self.session = session
        self.dump = dump

    def load_all(self) -> LoadResult:
        result = LoadResult()

        for raw_set in self.dump.fetch_sets():
            self._upsert_set(raw_set)
            result.sets_loaded += 1
            for raw_card in self.dump.fetch_cards(raw_set["id"]):
                self._upsert_card(raw_card, raw_set["id"])
                result.cards_loaded += 1

        self.session.commit()
        return result

    def _upsert_set(self, raw: dict[str, Any]) -> None:
        images = raw.get("images") or {}
        existing = self.session.get(CardSet, raw["id"])
        target = existing or CardSet(id=raw["id"])

        target.name = raw.get("name", "")
        target.series = raw.get("series")
        target.printed_total = raw.get("printedTotal")
        target.total = raw.get("total")
        target.ptcgo_code = raw.get("ptcgoCode")
        target.release_date = raw.get("releaseDate")
        target.image_symbol = images.get("symbol")
        target.image_logo = images.get("logo")

        if existing is None:
            self.session.add(target)

    def _upsert_card(self, raw: dict[str, Any], set_id: str) -> None:
        images = raw.get("images") or {}
        existing = self.session.get(Card, raw["id"])
        target = existing or Card(id=raw["id"])

        target.set_id = set_id
        target.name = raw.get("name", "")
        target.number = raw.get("number", "")
        target.rarity = raw.get("rarity")
        target.supertype = raw.get("supertype")
        target.subtypes = raw.get("subtypes")
        target.artist = raw.get("artist")
        target.national_pokedex_numbers = raw.get("nationalPokedexNumbers")
        target.image_small = images.get("small")
        target.image_large = images.get("large")

        if existing is None:
            self.session.add(target)
