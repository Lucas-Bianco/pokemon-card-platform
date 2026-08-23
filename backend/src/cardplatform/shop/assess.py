"""Online shopping assistant — assess an eBay listing URL (Phase E, roadmap row 18).

Read-only orchestration over the existing sealed catalog, card catalog, price
service, and authenticity modules. Given an eBay listing URL, it:

1. Extracts the item ID (pure regex, no network).
2. Fetches the live listing via the listings provider (no key -> unavailable,
   never raises; provider degrades to None on any error).
3. Matches the listing title to a sealed product (high confidence) or a card
   (low confidence) — sealed wins because sealed-product names are specific and
   the catalog is curated, while card-name substring matching is a best-effort
   heuristic.
4. Computes a deal edge against a proven market figure (eBay sold-comps median
   for sealed; PriceService.latest_price for cards). Honest empty states:
   market is None (never 0) when no comps / no snapshot, and every market
   figure carries source + source_updated_at.
5. For card matches only, runs the printed-number consistency check + the
   physical checklist — a guide, never a fake/real verdict (0 confirmed-
   counterfeit samples).

Sacred constraints held:
- Honest empty states: market None, edge None, "no market price" — NEVER $0,
  NEVER fabricate.
- Providers degrade to [] / None, NEVER raise. No key -> None WITHOUT a network
  call.
- Every market figure surfaces source + source_updated_at (staleness).
- func.lower(col).like(...), NOT ilike (SQLite ASCII-only).
- Authenticity is NEVER a fake/real verdict — a mismatch means "wrong title->
  catalog match OR counterfeit, indistinguishable".
- Read-only: no data/ writes, no new tables, no migrations.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.authenticity.checklist import ChecklistItem, checklist_for
from cardplatform.authenticity.consistency import ConsistencyResult, check_consistency
from cardplatform.config import Settings
from cardplatform.db.models import Card
from cardplatform.prices.ebay_listings import parse_ebay_item_id
from cardplatform.prices.service import PriceService
from cardplatform.sealed.catalog_service import SealedCatalogService


@dataclass(frozen=True)
class ShopListing:
    item_id: str
    title: str | None
    price: float | None
    currency: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    seller: str | None
    image_url: str | None
    url: str | None
    source: str = "ebay"


@dataclass(frozen=True)
class ShopMatch:
    kind: Literal["card", "sealed", "none"]
    confidence: Literal["high", "low"]
    card_id: str | None = None
    card_name: str | None = None
    card_number: str | None = None
    card_rarity: str | None = None
    set_name: str | None = None
    sealed_slug: str | None = None
    sealed_name: str | None = None


@dataclass(frozen=True)
class ShopDeal:
    market: float | None
    market_source: str | None
    market_source_updated_at: str | None
    sold_comps_count: int
    edge: float | None
    is_deal: bool
    min_abs: float
    min_pct: float
    market_unavailable: bool
    market_empty: bool


@dataclass(frozen=True)
class ShopAuthenticity:
    caveat: str
    consistency: ConsistencyResult
    checklist: list[ChecklistItem]


@dataclass(frozen=True)
class ShopAssessment:
    url: str
    item_id: str | None
    listing_unavailable: bool
    listing_not_found: bool
    listing: ShopListing | None
    match: ShopMatch
    deal: ShopDeal | None
    authenticity: ShopAuthenticity | None
    caveat: str


# The honest framing surfaced on every assessment — never a verdict. Authenticity
# is a guide with 0 confirmed-counterfeit samples; a mismatch means a wrong
# title->catalog match OR a counterfeit, indistinguishable to this app.
_ASSESSMENT_CAVEAT = (
    "An assessment, not a verdict. Market figures are proven eBay sold-comps or "
    "the catalog price with source + age; authenticity is a guide with 0 "
    "confirmed-counterfeit samples. A mismatch means a wrong title->catalog "
    "match OR a counterfeit — the app cannot tell which."
)

_AUTH_CAVEAT = (
    "A guide for what to check on the listing's photos, not a verdict. The "
    "printed-number check is read from the listing title, so a mismatch may "
    "mean the title->card match is wrong, not that the listing is fake."
)

# Printed collector number as "NN/NN" in a listing title (e.g. "Charizard 12/102").
# Group 1 is the numerator — the collector number; the denominator is the set
# size and is not part of the collector number (mirrors consistency._DENOM_RE).
_PRINTED_NUM_RE = re.compile(r"\b(\d{1,3})\s*/\s*\d{1,3}\b")


class ShopAssessor:
    """Assess an eBay listing URL: match -> deal -> authenticity (read-only)."""

    def __init__(self, session: Session, settings: Settings, provider) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider

    def assess(self, url: str, limit: int = 6) -> ShopAssessment:
        item_id = parse_ebay_item_id(url)
        key_set = bool(self.settings.listings_api_key)

        raw = self.provider.fetch_listing_by_id(item_id) if (item_id and key_set) else None

        listing: ShopListing | None = None
        if raw is not None:
            listing = ShopListing(
                item_id=item_id or "",
                title=raw.title,
                price=raw.price,
                currency=raw.currency,
                condition=raw.condition,
                listing_type=raw.listing_type,
                auction_end_at=raw.auction_end_at,
                seller=raw.seller,
                image_url=raw.image_url,
                url=raw.url,
                source="ebay",
            )

        listing_unavailable = not key_set
        listing_not_found = key_set and raw is None

        title = raw.title if raw else None
        match = self._match(title)

        deal = self._deal(raw, match, limit)
        authenticity = self._authenticity(match, title)

        return ShopAssessment(
            url=url,
            item_id=item_id,
            listing_unavailable=listing_unavailable,
            listing_not_found=listing_not_found,
            listing=listing,
            match=match,
            deal=deal,
            authenticity=authenticity,
            caveat=_ASSESSMENT_CAVEAT,
        )

    # ---- matching ----

    def _match(self, title: str | None) -> ShopMatch:
        if not title:
            return ShopMatch(kind="none", confidence="low")

        tlower = title.lower()

        # Sealed first: curated catalog, specific names — high confidence. The
        # catalog's search() is `name LIKE '%query%'` (name CONTAINS query), which
        # is backwards for a listing title: the title is always longer / more
        # verbose than the canonical product name, so querying with the full title
        # matches nothing. Search by the title's tokens instead, collect candidates,
        # then keep only products whose NAME is a substring of the TITLE (the
        # correct direction) and pick the longest name (most specific product).
        sealed_candidates: list = []
        seen_slugs: set[str] = set()
        try:
            tokens = sorted(
                (t for t in title.split() if len(t) >= 3),
                key=len,
                reverse=True,
            )
            svc = SealedCatalogService(self.session)
            for token in tokens:
                for c in svc.search(query=token):
                    if c.slug in seen_slugs:
                        continue
                    seen_slugs.add(c.slug)
                    sealed_candidates.append(c)
        except Exception:
            sealed_candidates = []
        sealed_hits = [c for c in sealed_candidates if c.name and c.name.lower() in tlower]
        if sealed_hits:
            best = max(sealed_hits, key=lambda c: len(c.name))
            return ShopMatch(
                kind="sealed",
                confidence="high",
                sealed_slug=best.slug,
                sealed_name=best.name,
            )

        # Card fallback: best-effort substring heuristic, low confidence. Try the
        # longest whitespace-delimited token that yields any card-name like match,
        # then among those matches keep cards whose name is a substring of the
        # title, picking the longest name. Wrapped so any DB error falls through
        # to "none" rather than raising.
        try:
            tokens = sorted(
                (t for t in title.split() if t),
                key=len,
                reverse=True,
            )
            matched_cards: list[Card] = []
            for token in tokens:
                stmt = select(Card).where(func.lower(Card.name).like(f"%{token}%"))
                rows = list(self.session.scalars(stmt).all())
                if rows:
                    matched_cards.extend(rows)
            # Dedupe by id while preserving order, then filter to name-substring
            # of the title (the token like may over-match).
            seen: set[str] = set()
            unique: list[Card] = []
            for c in matched_cards:
                if c.id in seen:
                    continue
                seen.add(c.id)
                if c.name and c.name.lower() in tlower:
                    unique.append(c)
            if unique:
                best = max(unique, key=lambda c: len(c.name or ""))
                return ShopMatch(
                    kind="card",
                    confidence="low",
                    card_id=best.id,
                    card_name=best.name,
                    card_number=best.number,
                    card_rarity=best.rarity,
                    set_name=best.card_set.name if best.card_set else None,
                )
        except Exception:
            pass

        return ShopMatch(kind="none", confidence="low")

    # ---- deal ----

    def _deal(self, raw, match: ShopMatch, limit: int) -> ShopDeal | None:
        if match.kind == "none" or raw is None:
            return None

        key_set = bool(self.settings.listings_api_key)

        if match.kind == "sealed":
            comps = self.provider.fetch_sold_listings_by_query(match.sealed_name, limit)
            if comps is None:
                comps = []
            prices = [c.price for c in comps if c.price is not None]
            market = statistics.median(prices) if prices else None
            market_source = "ebay" if market is not None else None
            market_source_updated_at = None
            sold_comps_count = len(comps)
            market_unavailable = not key_set
            market_empty = key_set and not comps
            min_abs = self.settings.sealed_flip_min_abs
            min_pct = self.settings.sealed_flip_min_pct
        else:
            # Card: PriceService with no provider is fine for latest_price (read-only).
            snap = PriceService(self.session).latest_price(match.card_id, "normal")
            market = snap.market if snap else None
            market_source = snap.source if snap else None
            # Coerce the "" sentinel to None — never surface an empty-string stamp.
            market_source_updated_at = (snap.source_updated_at or None) if snap else None
            sold_comps_count = 0
            market_unavailable = False
            market_empty = market is None
            min_abs = self.settings.deal_rip_min_abs
            min_pct = self.settings.deal_rip_min_pct

        edge = (market - raw.price) if (market is not None and raw.price is not None) else None
        is_deal = (
            edge is not None
            and market is not None
            and market > 0
            and edge >= min_abs
            and edge >= min_pct * market
        )

        return ShopDeal(
            market=market,
            market_source=market_source,
            market_source_updated_at=market_source_updated_at,
            sold_comps_count=sold_comps_count,
            edge=edge,
            is_deal=is_deal,
            min_abs=min_abs,
            min_pct=min_pct,
            market_unavailable=market_unavailable,
            market_empty=market_empty,
        )

    # ---- authenticity ----

    def _authenticity(self, match: ShopMatch, title: str | None) -> ShopAuthenticity | None:
        if match.kind != "card":
            return None

        printed: str | None = None
        if title:
            m = _PRINTED_NUM_RE.search(title)
            if m:
                printed = m.group(1)

        consistency = check_consistency(
            ocr_number=printed,
            card_number=match.card_number,
            card_id=match.card_id,
            card_name=match.card_name,
        )
        items = checklist_for(rarity=match.card_rarity, variant=None)
        return ShopAuthenticity(caveat=_AUTH_CAVEAT, consistency=consistency, checklist=items)