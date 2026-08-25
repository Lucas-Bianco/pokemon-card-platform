"""Vault import (roadmap row 30) — the symmetric pair to the Row 28 export.

Bulk-add holdings from a CSV or JSON file (e.g. one exported by the app, or a
spreadsheet you've kept elsewhere) into the vault, with honest skip-reporting
for rows the catalog doesn't recognise and rows that are malformed.

Honesty (the whole feature):
- Rows are inserted **directly** as `CollectionItem`s, not via
  `CollectionStore.add`. `add` tops up an existing (card_id, variant) row and
  always stamps `acquired_at = now`, which would discard the imported purchase
  date and collapse two dated acquisitions into one. Importing directly
  preserves `acquired_at` from the file so the Row 27 acquisition timeline
  stays accurate.
- A row whose `card_id` isn't in the catalog is **skipped with a reason**,
  never silently coerced or dropped. Unknown cards are reported, not guessed.
- A row missing its `card_id`, or with a quantity below 1, is skipped with a
  reason. Bad rows are skipped + reported, never silently fabricated.
- `acquired_price` / `condition` / `notes` are optional; an empty optional
  field is `None` (honest), never a fabricated $0 or placeholder.
- `acquired_at` is optional; an empty value is `None` (the holding is dated
  "added at import time" only if the caller leaves it null — the model's own
  default applies on insert only when the column is unset, and we set it
  explicitly to `None` so the row is genuinely undated, matching the export
  round-trip where a blank cell reads back as a null).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CollectionItem


_IMPORT_CAVEAT = (
    "Rows are inserted directly as holdings, preserving the imported acquired_at "
    "so the acquisition timeline stays accurate (acquired_at is not reset to now). "
    "A row whose card_id isn't in the catalog, or is missing its card_id, or has a "
    "quantity below 1, is skipped with a reason — never silently dropped or coerced. "
    "Optional empty fields (acquired_price, condition, notes, acquired_at) are null, "
    "never a fabricated $0."
)


@dataclass(frozen=True)
class ImportRow:
    """One parsed holding intent — already typed. The route layer is
    responsible for turning CSV/JSON cells into this; the importer is pure DB.

    `acquired_at` is an aware datetime (or `None` for an undated holding).
    """

    card_id: str
    variant: str = "normal"
    quantity: int = 1
    acquired_price: float | None = None
    acquired_at: datetime | None = None
    condition: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ImportSkip:
    """A row that was not imported, with an honest reason."""

    row_number: int
    card_id: str | None
    reason: str


@dataclass(frozen=True)
class ImportReport:
    """The outcome of an import. `total` is the number of input rows seen;
    `added` is how many became holdings; `skipped` lists the rest with reasons.

    The skipped list is never silently truncated; the route caps the input
    size before calling the importer so a 10k-row cap surfaces as a 400, not
    as a half-imported report.
    """

    total: int
    added: int
    skipped: list[ImportSkip] = field(default_factory=list)
    caveat: str = _IMPORT_CAVEAT


def import_holdings(session: Session, rows: list[ImportRow]) -> ImportReport:
    """Import `rows` into the vault. Inserts each valid row directly as a
    `CollectionItem` (preserving `acquired_at`), skips the rest with reasons,
    commits once at the end. Pure DB — no network, no data/ writes."""
    skipped: list[ImportSkip] = []
    added = 0

    for index, row in enumerate(rows, start=1):
        card_id = row.card_id.strip() if row.card_id else ""
        if card_id == "":
            skipped.append(ImportSkip(row_number=index, card_id=None, reason="missing card id"))
            continue
        card = session.get(Card, card_id)
        if card is None:
            skipped.append(
                ImportSkip(row_number=index, card_id=card_id, reason=f"unknown card: {card_id}")
            )
            continue
        if row.quantity < 1:
            skipped.append(
                ImportSkip(
                    row_number=index,
                    card_id=card_id,
                    reason=f"quantity must be >= 1, got {row.quantity}",
                )
            )
            continue

        variant = row.variant.strip() if row.variant else "normal"
        if variant == "":
            variant = "normal"
        item = CollectionItem(
            card_id=card_id,
            variant=variant,
            quantity=row.quantity,
            acquired_price=row.acquired_price,
            acquired_at=row.acquired_at,
            condition=row.condition,
            notes=row.notes,
        )
        session.add(item)
        added += 1

    session.commit()
    return ImportReport(total=len(rows), added=added, skipped=skipped, caveat=_IMPORT_CAVEAT)