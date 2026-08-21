"""Set-completion optimizer: per-set owned/missing checklist + honest cost to complete.

Read-only. Missing-card prices come through ``PriceService.latest_price`` — the sacred
price path, never ad-hoc. Owned cards are not priced here (they are already acquired);
pricing them is a deferred follow-up. No tables, no snapshots, no ``data/`` writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CardSet, CollectionItem
from cardplatform.prices.service import PriceService

# Natural collector-number sort. Plain numerics first ("1","2","10"); a numeric base
# with a suffix ("4a") sorts right after its base; a non-numeric prefix ("TG01","SV01")
# sorts after every plain numeric (promos/secret rares at the end of the checklist).
_NUM_RE = re.compile(r"^(\d+)(.*)$")
_SENTINEL = 10**9


def _number_sort_key(number: str | None) -> tuple[int, str]:
    m = _NUM_RE.match(number or "")
    if not m:
        return (_SENTINEL, number or "")
    return (int(m.group(1)), m.group(2))


@dataclass(frozen=True)
class SetProgress:
    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    owned: int
    checklist_size: int
    pct_complete: float


@dataclass(frozen=True)
class ChecklistEntry:
    card_id: str
    name: str
    number: str
    rarity: str | None
    image_small: str | None
    owned: bool
    market: float | None
    source: str | None
    source_updated_at: str | None


@dataclass(frozen=True)
class CompletionSummary:
    owned: int
    checklist_size: int
    missing: int
    pct_complete: float
    est_cost_to_complete: float | None
    unpriced_missing: int


@dataclass(frozen=True)
class SetCompletion:
    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    cards: list[ChecklistEntry]
    summary: CompletionSummary


class CompletionService:
    def __init__(self, session: Session, price_service: PriceService) -> None:
        self.session = session
        self.price_service = price_service

    def list_sets(self, query: str | None = None) -> list[SetProgress]:
        stmt = select(CardSet)
        if query:
            # lower() not ilike(): SQLite LIKE is ASCII-only case-insensitive; the
            # catalog carries accented names. Sacred constraint.
            stmt = stmt.where(func.lower(CardSet.name).like(f"%{query.lower()}%"))
        stmt = stmt.order_by(CardSet.release_date.desc(), CardSet.name)
        sets = list(self.session.scalars(stmt).all())

        owned_counts = dict(
            self.session.execute(
                select(Card.set_id, func.count(func.distinct(CollectionItem.card_id)))
                .join(CollectionItem, CollectionItem.card_id == Card.id)
                .group_by(Card.set_id)
            ).all()
        )
        checklist_counts = dict(
            self.session.execute(
                select(Card.set_id, func.count()).group_by(Card.set_id)
            ).all()
        )

        out: list[SetProgress] = []
        for s in sets:
            size = checklist_counts.get(s.id, 0)
            owned = owned_counts.get(s.id, 0)
            out.append(
                SetProgress(
                    id=s.id,
                    name=s.name,
                    series=s.series,
                    release_date=s.release_date,
                    total=s.total,
                    printed_total=s.printed_total,
                    owned=owned,
                    checklist_size=size,
                    pct_complete=(owned / size) if size else 0,
                )
            )
        return out

    def set_detail(self, set_id: str) -> SetCompletion:
        s = self.session.get(CardSet, set_id)
        if s is None:
            raise LookupError(f"unknown set: {set_id!r}")

        cards = list(
            self.session.scalars(select(Card).where(Card.set_id == set_id)).all()
        )
        owned_ids = set(
            self.session.scalars(
                select(CollectionItem.card_id)
                .join(Card, Card.id == CollectionItem.card_id)
                .where(Card.set_id == set_id)
            ).all()
        )

        entries: list[ChecklistEntry] = []
        for c in sorted(cards, key=lambda card: _number_sort_key(card.number)):
            owned = c.id in owned_ids
            market: float | None = None
            source: str | None = None
            source_updated_at: str | None = None
            if not owned:
                snap = self.price_service.latest_price(c.id, "normal")
                if snap is not None:
                    market = snap.market
                    source = snap.source
                    # "" sentinel (no source timestamp) -> None on the wire.
                    source_updated_at = snap.source_updated_at or None
            entries.append(
                ChecklistEntry(
                    card_id=c.id,
                    name=c.name,
                    number=c.number,
                    rarity=c.rarity,
                    image_small=c.image_small,
                    owned=owned,
                    market=market,
                    source=source,
                    source_updated_at=source_updated_at,
                )
            )

        owned = len(owned_ids)
        checklist_size = len(cards)
        missing = checklist_size - owned
        missing_entries = [e for e in entries if not e.owned]
        priced_missing = [e for e in missing_entries if e.market is not None]
        if missing == 0:
            est_cost: float | None = 0.0
        elif priced_missing:
            est_cost = sum(e.market for e in priced_missing)
        else:
            est_cost = None
        unpriced_missing = len(missing_entries) - len(priced_missing)

        summary = CompletionSummary(
            owned=owned,
            checklist_size=checklist_size,
            missing=missing,
            pct_complete=(owned / checklist_size) if checklist_size else 0,
            est_cost_to_complete=est_cost,
            unpriced_missing=unpriced_missing,
        )
        return SetCompletion(
            id=s.id,
            name=s.name,
            series=s.series,
            release_date=s.release_date,
            total=s.total,
            printed_total=s.printed_total,
            cards=entries,
            summary=summary,
        )