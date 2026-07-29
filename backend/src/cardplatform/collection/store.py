"""Owns collection rows and values them against the latest recorded prices."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CollectionItem
from cardplatform.prices.service import PriceService


@dataclass(frozen=True)
class Valuation:
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


class CollectionStore:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.prices = PriceService(session)

    def add(
        self,
        card_id: str,
        variant: str = "normal",
        quantity: int = 1,
        acquired_price: float | None = None,
        condition: str | None = None,
        notes: str | None = None,
    ) -> CollectionItem:
        """Add copies of a card. Re-adding the same (card_id, variant) tops up the
        existing row so a collection holds one row per printing, not one per purchase."""
        if self.session.get(Card, card_id) is None:
            raise ValueError(f"unknown card: {card_id!r}")

        item = self._find(card_id, variant)
        if item is None:
            item = CollectionItem(
                card_id=card_id,
                variant=variant,
                quantity=quantity,
                acquired_price=acquired_price,
                condition=condition,
                notes=notes,
            )
            self.session.add(item)
        else:
            item.quantity += quantity
        self.session.commit()
        return item

    def remove(self, card_id: str, variant: str = "normal", quantity: int = 1) -> None:
        """Remove copies. Removing more than held, or a card never held, is a no-op
        rather than an error — callers should not have to check first."""
        item = self._find(card_id, variant)
        if item is None:
            return

        item.quantity -= quantity
        if item.quantity <= 0:
            self.session.delete(item)
        self.session.commit()

    def list_items(self) -> list[CollectionItem]:
        return list(
            self.session.scalars(select(CollectionItem).order_by(CollectionItem.id)).all()
        )

    def total_value(self) -> Valuation:
        """Value the collection conservatively: an item we cannot price contributes
        nothing to market value and is counted, never estimated from a neighbour."""
        market_value = 0.0
        cost_basis = 0.0
        unpriced_items = 0

        for item in self.list_items():
            if item.acquired_price is not None:
                cost_basis += item.acquired_price * item.quantity

            snapshot = self.prices.latest_price(item.card_id, item.variant)
            if snapshot is None or snapshot.market is None:
                unpriced_items += 1
                continue
            market_value += snapshot.market * item.quantity

        return Valuation(
            market_value=market_value,
            cost_basis=cost_basis,
            unrealized=market_value - cost_basis,
            unpriced_items=unpriced_items,
        )

    def _find(self, card_id: str, variant: str) -> CollectionItem | None:
        return self.session.scalars(
            select(CollectionItem).where(
                CollectionItem.card_id == card_id,
                CollectionItem.variant == variant,
            )
        ).first()
