"""Shareable binder — a curated, ordered subset of your vault (roadmap row 21).

The binder is NOT a second copy of `collection_items`; it is a thin ordered
reference list of (card, variant) slots you curate to show off a PC. Each slot
carries an optional free-form note and a manual `sort_order`. At read time each
slot is joined to its catalog row (name / set / image) and, when a sold-comps
provider is wired, to its single most-recent *proven* eBay sale — the honest
backing for every price the binder shows. A slot with no proven sale is an em
dash + "no proven sale", never a fabricated `$0`. The provider degrades to `[]`
and never raises, so a keyless server simply shows the binder without sale chips.

`export_html` renders the binder as a single self-contained HTML document (inline
CSS, hotlinked card images, a proven-sale line per card) — the "shareable"
artifact is a file you download and host/attach anywhere, not a promise that the
server publishes a public page (local-first: no server uptime required to share).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.db.models import BinderItem, Card


@dataclass(frozen=True)
class ProvenSale:
    """The single most-recent proven eBay sale backing a binder slot.

    `price` is the actual transaction price (a SoldComp always carries one).
    The whole object is `None` when there is no proven sale — the UI shows an em
    dash, never `$0`.
    """

    listing_id: str
    title: str | None
    price: float
    currency: str | None
    url: str | None
    condition: str | None
    sold_at: Any  # tz-aware datetime | None
    source: str


@dataclass(frozen=True)
class BinderEntry:
    """One binder slot joined to its catalog row + proven sale.

    `proven_sale` is None when there is no proven sale. `proven_sale_unavailable`
    is True when no provider/key is configured at all (so the UI can say "set an
    eBay key to prove sales" rather than "this card has no sales"); `proven_sale_empty`
    is True when a key IS set but eBay returned no comps for this card.
    """

    card_id: str
    variant: str
    sort_order: int
    note: str | None
    added_at: Any  # tz-aware datetime
    card_name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    image_large: str | None
    proven_sale: ProvenSale | None
    proven_sale_unavailable: bool
    proven_sale_empty: bool


class _SoldCompsProvider(Protocol):
    """The slice of `EbayListingsProvider` the binder needs. Defined locally so
    the service is testable with a tiny stub and avoids importing the
    network-bearing provider at module load."""

    def fetch_sold_listings(
        self, card_id: str, variant: str, limit: int = 3
    ) -> list: ...


class BinderService:
    """Curates the binder. Add/remove/reorder/set_note mutate; list/export read.
    Never raises out of a provider call — a missing provider yields an honest
    `proven_sale_unavailable` slot, an empty result yields `proven_sale_empty`."""

    def __init__(
        self,
        session: Session,
        sold_comps_provider: _SoldCompsProvider | None = None,
        *,
        listings_api_key_set: bool = False,
    ) -> None:
        self.session = session
        self.sold_comps = sold_comps_provider
        # True when the server has an eBay key configured (the provider can talk
        # to eBay). Distinguishes "no key" from "key but no comps for this card".
        self._key_set = listings_api_key_set

    # ----------------------------------------------------------- mutators

    def add(self, card_id: str, variant: str = "normal", note: str | None = None) -> BinderItem:
        """Add a slot to the binder. Raises LookupError for an unknown card and
        ValueError if the slot already exists (one per card-variant). The new
        slot is appended at the end (sort_order = current max + 1)."""
        card = self.session.get(Card, card_id)
        if card is None:
            raise LookupError(f"unknown card: {card_id!r}")
        existing = self.session.scalars(
            select(BinderItem).where(
                BinderItem.card_id == card_id, BinderItem.variant == variant
            )
        ).first()
        if existing is not None:
            raise ValueError(f"already in binder: {card_id!r} / {variant!r}")

        max_order = self.session.scalar(
            select(func.max(BinderItem.sort_order))
        )
        next_order = (max_order or 0) + 1
        item = BinderItem(
            card_id=card_id, variant=variant, sort_order=next_order, note=note
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def remove(self, card_id: str, variant: str = "normal") -> bool:
        """Remove a slot. Returns True if a row was deleted, False if the slot
        wasn't in the binder. Does NOT renumber the surviving slots (gaps in
        sort_order are harmless — list_items orders by sort_order regardless)."""
        item = self.session.scalars(
            select(BinderItem).where(
                BinderItem.card_id == card_id, BinderItem.variant == variant
            )
        ).first()
        if item is None:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def set_note(self, card_id: str, variant: str = "normal", note: str | None = None) -> BinderItem:
        """Set or clear a slot's note. Raises LookupError if the slot isn't in the
        binder. Pass note=None to clear."""
        item = self.session.scalars(
            select(BinderItem).where(
                BinderItem.card_id == card_id, BinderItem.variant == variant
            )
        ).first()
        if item is None:
            raise LookupError(f"not in binder: {card_id!r} / {variant!r}")
        item.note = note
        self.session.commit()
        self.session.refresh(item)
        return item

    def reorder(self, ordered_keys: list[tuple[str, str]]) -> None:
        """Reassign sort_order to match the supplied (card_id, variant) order.
        Keys are applied in the order given (0..n-1); any binder slots NOT named
        in the list keep their current relative order, appended after the named
        ones. Unknown keys in the list are ignored (they aren't in the binder).
        A slot appearing more than once keeps its last position."""
        current = self.session.scalars(
            select(BinderItem).order_by(BinderItem.sort_order)
        ).all()
        by_key = {(item.card_id, item.variant): item for item in current}

        # Named slots, in the caller's order, deduped (last occurrence wins: a
        # slot listed twice keeps its final position, so reorder is idempotent-ish
        # even if the caller repeats a key).
        last_pos: dict[tuple[str, str], int] = {}
        for i, key in enumerate(ordered_keys):
            if key in by_key:
                last_pos[key] = i
        named_order = [k for k, _ in sorted(last_pos.items(), key=lambda kv: kv[1])]
        # Surviving unnamed slots keep their current relative order.
        named_set = set(last_pos)
        unnamed = [
            (item.card_id, item.variant)
            for item in current
            if (item.card_id, item.variant) not in named_set
        ]
        full = named_order + unnamed
        for idx, key in enumerate(full):
            by_key[key].sort_order = idx
        self.session.commit()

    # ------------------------------------------------------------- readers

    def list_items(self) -> list[BinderEntry]:
        """All binder slots in sort_order, each joined to its catalog row and
        most-recent proven sale. Read-only — never writes, never raises out of
        the provider."""
        rows = self.session.scalars(
            select(BinderItem).order_by(BinderItem.sort_order, BinderItem.id)
        ).all()
        entries: list[BinderEntry] = []
        for item in rows:
            card = item.card
            if card is None:
                # FK dangled (card deleted) — skip rather than crash the whole list.
                continue
            set_name = card.card_set.name if card.card_set is not None else ""
            proven = self._proven_sale(item.card_id, item.variant)
            entries.append(
                BinderEntry(
                    card_id=item.card_id,
                    variant=item.variant,
                    sort_order=item.sort_order,
                    note=item.note,
                    added_at=item.added_at,
                    card_name=card.name,
                    set_id=card.set_id,
                    set_name=set_name,
                    number=card.number,
                    rarity=card.rarity,
                    image_small=card.image_small,
                    image_large=card.image_large,
                    proven_sale=proven.sale,
                    proven_sale_unavailable=proven.unavailable,
                    proven_sale_empty=proven.empty,
                )
            )
        return entries

    def export_html(self, title: str = "My Pokémon Binder") -> str:
        """Render the binder as a standalone self-contained HTML document.
        Inline CSS, hotlinked card images, a proven-sale line per card (or an
        honest "no proven sale yet" where there is none). The result is a file
        you download and share — no server uptime required."""
        entries = self.list_items()
        rows_html: list[str] = []
        for e in entries:
            rows_html.append(self._render_slot(e))
        return _HTML_TEMPLATE.format(
            title=html.escape(title),
            count=len(entries),
            rows="\n".join(rows_html),
            generated_note="Each price is a recent eBay *sold* listing — an actual transaction, not a listed ask. No proven sale is shown honestly, never a fabricated figure.",
        )

    # ----------------------------------------------------------- internals

    def _proven_sale(self, card_id: str, variant: str) -> "_ProvenResult":
        comps = (
            self.sold_comps.fetch_sold_listings(card_id, variant, 1)
            if self.sold_comps is not None
            else []
        )
        if not comps:
            unavailable = not self._key_set or self.sold_comps is None
            return _ProvenResult(sale=None, unavailable=unavailable, empty=(not unavailable))
        c = comps[0]
        return _ProvenResult(
            sale=ProvenSale(
                listing_id=c.listing_id,
                title=c.title,
                price=c.price,
                currency=c.currency,
                url=c.url,
                condition=c.condition,
                sold_at=c.sold_at,
                source=c.source,
            ),
            unavailable=False,
            empty=False,
        )

    @staticmethod
    def _render_slot(e: BinderEntry) -> str:
        img = e.image_large or e.image_small or ""
        img_tag = (
            f'<img class="card-img" src="{html.escape(img)}" alt="{html.escape(e.card_name)}">'
            if img
            else '<div class="card-img ph">no image</div>'
        )
        note_html = (
            f'<p class="note">{html.escape(e.note)}</p>' if e.note else ""
        )
        if e.proven_sale is not None:
            sale = e.proven_sale
            price_txt = f"{sale.price:.2f}".rstrip("0").rstrip(".") or "0"
            if sale.currency:
                price_txt = f"{sale.currency} {price_txt}"
            sold_txt = sale.sold_at.strftime("%Y-%m-%d") if sale.sold_at else "recently"
            sale_html = (
                f'<p class="sale">Proven sale: <strong>{html.escape(price_txt)}</strong> '
                f"· {html.escape(sold_txt)} · {html.escape(sale.condition or '—')}</p>"
            )
            if sale.url:
                sale_html = (
                    f'<p class="sale">Proven sale: <strong>{html.escape(price_txt)}</strong> '
                    f'· {html.escape(sold_txt)} · {html.escape(sale.condition or "—")} · '
                    f'<a href="{html.escape(sale.url)}" target="_blank" rel="noopener">listing</a></p>'
                )
        elif e.proven_sale_unavailable:
            sale_html = '<p class="sale none">No proven sale — set an eBay key to back prices with transactions.</p>'
        else:
            sale_html = '<p class="sale none">No proven sale yet.</p>'
        return (
            f'<div class="slot">\n'
            f"  {img_tag}\n"
            f'  <div class="meta">\n'
            f'    <h3>{html.escape(e.card_name)}</h3>\n'
            f'    <p class="sub">{html.escape(e.set_name)} · #{html.escape(e.number)}'
            f'{(" · " + html.escape(e.rarity)) if e.rarity else ""}'
            f" · {html.escape(e.variant)}</p>\n"
            f"    {note_html}\n"
            f"    {sale_html}\n"
            f"  </div>\n"
            f"</div>"
        )


@dataclass(frozen=True)
class _ProvenResult:
    sale: ProvenSale | None
    unavailable: bool
    empty: bool


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#0e1116; --card:#161b22; --ink:#e6edf3; --mut:#8b949e; --acc:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  header {{ padding:32px 24px 8px; max-width:960px; margin:0 auto; }}
  header h1 {{ margin:0 0 4px; font-size:28px; }}
  header p {{ margin:0; color:var(--mut); }}
  main {{ max-width:960px; margin:0 auto; padding:16px 24px 48px;
    display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px; }}
  .slot {{ background:var(--card); border:1px solid #232a35; border-radius:12px;
    padding:16px; display:flex; flex-direction:column; gap:12px; }}
  .card-img {{ width:100%; aspect-ratio:2.5/3.5; object-fit:cover; border-radius:8px;
    background:#0b0e13; }}
  .card-img.ph {{ display:flex; align-items:center; justify-content:center; color:var(--mut); }}
  .meta h3 {{ margin:0 0 4px; font-size:16px; }}
  .meta .sub {{ margin:0; color:var(--mut); font-size:13px; }}
  .meta .note {{ margin:8px 0 0; color:var(--ink); font-style:italic; }}
  .sale {{ margin:8px 0 0; font-size:13px; color:var(--ink); }}
  .sale.none {{ color:var(--mut); }}
  .sale a {{ color:var(--acc); }}
  footer {{ max-width:960px; margin:0 auto; padding:0 24px 48px; color:var(--mut); font-size:13px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{count} card(s)</p>
</header>
<main>
{rows}
</main>
<footer>{generated_note}</footer>
</body>
</html>
"""