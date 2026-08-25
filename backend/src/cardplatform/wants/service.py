"""Want list / hunt list service (roadmap row 24).

The want list is a planning surface — cards you want to *acquire*, distinct
from the binder (cards you own and show off) and from alerts (which watch
listing conditions). A slot is `(card_id, variant)` and is unique, so each card
occupies at most one row in the want list.

`WantService` mirrors `BinderService` but is simpler: no reorder, no export,
no sold-comps provider. It carries an optional `target_price` (what you'd be
willing to pay — nullable, honest "no target") and a free-form note.

At read time each slot is joined to its catalog row and to the same
`PriceService.latest_price` the rest of the app uses — never a fabricated
figure. When both `target_price` and a resolved `market_price` are present we
compute `deal_gap = target_price - market_price` (positive = under your cap,
room to spare; negative = over your cap) and `within_target = market_price <=
target_price`. When either is missing these stay `None` (honest unknown), and
`market_price` is `None` (never a fabricated `$0`).

A dangled FK (a want row whose card was deleted from the catalog) is skipped at
read time — never surfaced as a half-blank row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, WantItem
from cardplatform.prices.service import PriceService


@dataclass(frozen=True)
class WantEntry:
    """One want-list slot joined to its catalog row + market reference.

    Every market field is `None` when there is no price — never a fabricated
    `$0`. `deal_gap`/`within_target` are `None` when either side is missing,
    never a guess.
    """

    card_id: str
    variant: str
    target_price: float | None
    note: str | None
    added_at: datetime

    card_name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    image_large: str | None

    market_price: float | None
    market_source: str | None
    market_source_updated_at: str | None
    deal_gap: float | None
    within_target: bool | None


class WantService:
    """Reads/writes the want list. Pure DB + `PriceService`; no network."""

    def __init__(self, session: Session, price_service: PriceService | None = None) -> None:
        self.session = session
        self.prices = price_service if price_service is not None else PriceService(session)

    def add(
        self,
        card_id: str,
        variant: str = "normal",
        target_price: float | None = None,
        note: str | None = None,
    ) -> WantEntry:
        """Add a slot. Raises `LookupError` if the card isn't in the catalog,
        `ValueError` if the slot already exists. Returns the new entry."""
        card = self.session.get(Card, card_id)
        if card is None:
            raise LookupError(f"unknown card: {card_id}")
        existing = self._find(card_id, variant)
        if existing is not None:
            raise ValueError(f"want slot already exists: {card_id}/{variant}")
        row = WantItem(
            card_id=card_id,
            variant=variant,
            target_price=target_price,
            note=note,
        )
        self.session.add(row)
        self.session.flush()
        return self._entry(row, card)

    def remove(self, card_id: str, variant: str = "normal") -> bool:
        """Remove a slot. Returns True if removed, False if it wasn't there.
        Never raises — deleting a missing want is a no-op."""
        row = self._find(card_id, variant)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def set_target_price(
        self, card_id: str, variant: str = "normal", target_price: float | None = None
    ) -> WantEntry:
        """Set or clear the target price. `target_price=None` clears it (honest
        "no target"). Raises `LookupError` if the slot isn't in the want list."""
        row = self._find(card_id, variant)
        if row is None:
            raise LookupError(f"want slot not found: {card_id}/{variant}")
        row.target_price = target_price
        self.session.flush()
        return self._entry(row, self.session.get(Card, card_id))

    def set_note(self, card_id: str, variant: str = "normal", note: str | None = None) -> WantEntry:
        """Set or clear the note. `note=None` clears it. Raises `LookupError`
        if the slot isn't in the want list."""
        row = self._find(card_id, variant)
        if row is None:
            raise LookupError(f"want slot not found: {card_id}/{variant}")
        row.note = note
        self.session.flush()
        return self._entry(row, self.session.get(Card, card_id))

    def list_items(self) -> list[WantEntry]:
        """All want slots, oldest-first, joined to catalog + market price.

        Slots whose card was deleted from the catalog are skipped (dangled FK),
        never surfaced as half-blank rows.
        """
        rows = (
            self.session.execute(
                select(WantItem).order_by(WantItem.added_at.asc(), WantItem.id.asc())
            )
            .scalars()
            .all()
        )
        out: list[WantEntry] = []
        for row in rows:
            card = row.card
            if card is None:
                continue
            out.append(self._entry(row, card))
        return out

    # -- internals -----------------------------------------------------

    def _find(self, card_id: str, variant: str) -> WantItem | None:
        return self.session.execute(
            select(WantItem).where(
                WantItem.card_id == card_id,
                WantItem.variant == variant,
            )
        ).scalar_one_or_none()

    def _entry(self, row: WantItem, card: Card) -> WantEntry:
        snap = self.prices.latest_price(card.id, row.variant)
        market_price = snap.market if snap is not None else None
        market_source = snap.source if snap is not None else None
        market_source_updated_at = snap.source_updated_at if snap is not None else None

        deal_gap: float | None = None
        within_target: bool | None = None
        if row.target_price is not None and market_price is not None:
            deal_gap = row.target_price - market_price
            within_target = market_price <= row.target_price

        set_name = card.card_set.name if card.card_set is not None else ""
        return WantEntry(
            card_id=row.card_id,
            variant=row.variant,
            target_price=row.target_price,
            note=row.note,
            added_at=row.added_at,
            card_name=card.name,
            set_id=card.set_id,
            set_name=set_name,
            number=card.number,
            rarity=card.rarity,
            image_small=card.image_small,
            image_large=card.image_large,
            market_price=market_price,
            market_source=market_source,
            market_source_updated_at=market_source_updated_at,
            deal_gap=deal_gap,
            within_target=within_target,
        )