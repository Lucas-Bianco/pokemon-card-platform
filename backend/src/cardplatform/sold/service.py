"""Realized gains / sold-lot service (roadmap row 29).

The disposal counterpart to `CollectionStore`: a permanent, append-only ledger
of cards you've *sold*. A sale is an immutable event — `SoldLot` rows are
inserted once, never updated. `acquired_price` is the per-unit cost basis
**snapshotted at sale time**, so realized P/L is fixed against the cost you
actually paid and never recomputed against a holding you may have since
edited, reduced, or deleted.

Honesty (the whole feature):
- `proceeds` = (sale_price - (sale_fee or 0)) * quantity. A sale has a price,
  so proceeds are always known — never null, never a fabricated $0.
- `cost_basis` = acquired_price * quantity, or `None` when no cost basis was
  recorded at sale time. A sale without a known cost has unknown gain.
- `realized` = proceeds - cost_basis, or `None` when `cost_basis` is None.
  Never a fabricated $0 — an unknown gain is shown as such, not guessed.
- `summary.total_realized` is computed over the lots WITH a cost basis only;
  lots without one are counted in `lots_without_cost` and excluded from
  realized, never silently $0. `total_proceeds` sums ALL sales (a price is
  always present).

A dangled FK (a sold lot whose card was deleted from the catalog) is skipped
at read time — never surfaced as a half-blank row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, SoldLot


_SOLD_CAVEAT = (
    "Realized P/L is (sale price - fee) x quantity minus the cost basis "
    "snapshotted at sale time, computed only over lots with a recorded cost "
    "basis; lots without a cost basis are counted but excluded from realized, "
    "never $0. Proceeds sum all sales (a sale always has a price)."
)


@dataclass(frozen=True)
class SoldEntry:
    """One sold lot joined to its catalog row + derived money fields.

    `cost_basis`/`realized` are `None` when no cost basis was recorded — never
    a fabricated `$0`. `proceeds` is always known (a sale has a price).
    """

    id: int
    card_id: str
    variant: str
    quantity: int
    sale_price: float
    sale_fee: float | None
    acquired_price: float | None
    sold_at: datetime
    source: str | None
    notes: str | None

    card_name: str
    set_id: str
    set_name: str
    number: str

    proceeds: float
    cost_basis: float | None
    realized: float | None


@dataclass(frozen=True)
class SoldSummary:
    """Aggregate over the sold-lots ledger."""

    lot_count: int
    lots_with_cost: int
    lots_without_cost: int
    total_proceeds: float
    total_cost_basis: float
    total_realized: float
    winners: int
    losers: int
    caveat: str


class SoldLotService:
    """Reads/writes the sold-lots ledger. Pure DB; no network."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        card_id: str,
        variant: str = "normal",
        quantity: int = 1,
        sale_price: float = 0.0,
        sale_fee: float | None = None,
        acquired_price: float | None = None,
        sold_at: datetime | None = None,
        source: str | None = None,
        notes: str | None = None,
    ) -> SoldEntry:
        """Record a sale. Raises `LookupError` if the card isn't in the
        catalog, `ValueError` for a non-positive quantity or negative sale
        price. `sold_at` defaults to now (aware). Returns the new entry."""
        card = self.session.get(Card, card_id)
        if card is None:
            raise LookupError(f"unknown card: {card_id}")
        if quantity < 1:
            raise ValueError(f"quantity must be >= 1, got {quantity}")
        if sale_price < 0:
            raise ValueError(f"sale_price must be >= 0, got {sale_price}")
        if sold_at is None:
            sold_at = datetime.now(timezone.utc)
        row = SoldLot(
            card_id=card_id,
            variant=variant,
            quantity=quantity,
            sale_price=sale_price,
            sale_fee=sale_fee,
            acquired_price=acquired_price,
            sold_at=sold_at,
            source=source,
            notes=notes,
        )
        self.session.add(row)
        self.session.flush()
        return self._entry(row, card)

    def remove(self, lot_id: int) -> bool:
        """Delete a sold lot (mistake correction). Returns True if removed,
        False if it wasn't there. Never raises."""
        row = self.session.get(SoldLot, lot_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def list_lots(self) -> list[SoldEntry]:
        """All sold lots, oldest sale-first, joined to catalog.

        Lots whose card was deleted from the catalog are skipped (dangled FK),
        never surfaced as half-blank rows.
        """
        rows = (
            self.session.execute(
                select(SoldLot).order_by(SoldLot.sold_at.asc(), SoldLot.id.asc())
            )
            .scalars()
            .all()
        )
        out: list[SoldEntry] = []
        for row in rows:
            card = row.card
            if card is None:
                continue
            out.append(self._entry(row, card))
        return out

    def summary(self) -> SoldSummary:
        """Aggregate over the ledger. Realized is over the cost-known subset
        only; lots without a cost basis are counted but excluded, never $0."""
        rows = (
            self.session.execute(select(SoldLot).order_by(SoldLot.id.asc()))
            .scalars()
            .all()
        )
        lot_count = 0
        lots_with_cost = 0
        lots_without_cost = 0
        total_proceeds = 0.0
        total_cost_basis = 0.0
        total_realized = 0.0
        winners = 0
        losers = 0
        for row in rows:
            lot_count += 1
            proceeds = (row.sale_price - (row.sale_fee or 0.0)) * row.quantity
            total_proceeds += proceeds
            if row.acquired_price is not None:
                cost = (row.acquired_price or 0.0) * row.quantity
                realized = proceeds - cost
                lots_with_cost += 1
                total_cost_basis += cost
                total_realized += realized
                if realized > 0:
                    winners += 1
                elif realized < 0:
                    losers += 1
            else:
                lots_without_cost += 1
        return SoldSummary(
            lot_count=lot_count,
            lots_with_cost=lots_with_cost,
            lots_without_cost=lots_without_cost,
            total_proceeds=total_proceeds,
            total_cost_basis=total_cost_basis,
            total_realized=total_realized,
            winners=winners,
            losers=losers,
            caveat=_SOLD_CAVEAT,
        )

    # -- internals -----------------------------------------------------

    def _entry(self, row: SoldLot, card: Card) -> SoldEntry:
        proceeds = (row.sale_price - (row.sale_fee or 0.0)) * row.quantity
        if row.acquired_price is not None:
            cost_basis = (row.acquired_price or 0.0) * row.quantity
            realized = proceeds - cost_basis
        else:
            cost_basis = None
            realized = None
        set_name = card.card_set.name if card.card_set is not None else ""
        return SoldEntry(
            id=row.id,
            card_id=row.card_id,
            variant=row.variant,
            quantity=row.quantity,
            sale_price=row.sale_price,
            sale_fee=row.sale_fee,
            acquired_price=row.acquired_price,
            sold_at=row.sold_at,
            source=row.source,
            notes=row.notes,
            card_name=card.name,
            set_id=card.set_id,
            set_name=set_name,
            number=card.number,
            proceeds=proceeds,
            cost_basis=cost_basis,
            realized=realized,
        )