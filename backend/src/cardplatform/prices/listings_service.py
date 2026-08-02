"""Writes listing snapshots and answers latest-listing queries.

Mirrors GradedPriceService: snapshots are immutable and deduplicated on the
source's own freshness stamp (source_updated_at), so re-running a refresh does
not inflate history with identical rows. The empty-string sentinel for a
missing stamp matches ListingSnapshot's unique constraint (see models.py):
NULLs are distinct under a SQLite unique constraint, so a None stamp is stored
as "" to collide correctly instead of silently duplicating.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import ListingSnapshot
from cardplatform.prices.listings_provider import ListingsProvider


class ListingsService:
    def __init__(self, session: Session, provider: ListingsProvider | None = None) -> None:
        # provider is optional so read-only consumers (e.g. the alert diff in
        # T3) can construct the service just for latest_listings /
        # previous_listing_ids without wiring up a fetcher.
        self.session = session
        self.provider = provider

    def refresh_listings(self, card_id: str, variant: str) -> int:
        """Fetch and persist new listing snapshots. Returns rows written.

        Returns 0 (NOT an error) when the provider returns [] — that is the
        honest "no listings available" state (no API key, 404, transport
        failure after retries). Only raises when the service itself was
        constructed without a provider, mirroring GradedPriceService.
        """
        if self.provider is None:
            raise RuntimeError(
                "ListingsService was constructed without a provider; "
                "refresh_listings is unavailable"
            )
        written = 0
        for quote in self.provider.fetch_listings(card_id, variant):
            stamp = quote.source_updated_at or ""
            if self._already_recorded(
                card_id, variant, quote.source, quote.listing_id, stamp
            ):
                continue
            self.session.add(
                ListingSnapshot(
                    card_id=quote.card_id,
                    variant=quote.variant,
                    source=quote.source,
                    listing_id=quote.listing_id,
                    title=quote.title,
                    price=quote.price,
                    currency=quote.currency,
                    listing_type=quote.listing_type,
                    auction_end_at=quote.auction_end_at,
                    url=quote.url,
                    condition=quote.condition,
                    source_updated_at=stamp,
                )
            )
            written += 1
        self.session.commit()
        return written

    def _already_recorded(
        self,
        card_id: str,
        variant: str,
        source: str,
        listing_id: str,
        source_updated_at: str,
    ) -> bool:
        existing = self.session.scalars(
            select(ListingSnapshot.id).where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
                ListingSnapshot.source == source,
                ListingSnapshot.listing_id == listing_id,
                ListingSnapshot.source_updated_at == source_updated_at,
            )
        ).first()
        return existing is not None

    def latest_listings(self, card_id: str, variant: str) -> list[ListingSnapshot]:
        """The rows from the newest fetched_at snapshot for this (card_id,
        variant) — all sources together. Ordered price ASC with NULLS LAST so
        priced listings come before unpriced ones in the UI. Returns [] if
        none.

        fetched_at ties (Windows clock ~15ms granularity within a single
        flush) are broken by the id-tiebreak the DB default already provides —
        we filter on the exact max fetched_at, so any ties share that timestamp.
        """
        latest_fetched = self.session.scalars(
            select(ListingSnapshot.fetched_at)
            .where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
            )
            .order_by(ListingSnapshot.fetched_at.desc())
            .limit(1)
        ).first()
        if latest_fetched is None:
            return []
        rows = self.session.scalars(
            select(ListingSnapshot)
            .where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
                ListingSnapshot.fetched_at == latest_fetched,
            )
            .order_by(
                ListingSnapshot.price.is_(None),
                ListingSnapshot.price.asc(),
                ListingSnapshot.id.asc(),
            )
        ).all()
        return list(rows)

    def has_stock(self, card_id: str, variant: str) -> bool:
        """True if the latest snapshot has at least one listing for this card."""
        return bool(self.latest_listings(card_id, variant))

    def lowest_price(self, card_id: str, variant: str) -> float | None:
        """Min price over the latest snapshot where price is not None. None if
        none — NEVER 0.0 fabricated (a listing literally priced 0.0 is real
        data and is returned as-is)."""
        rows = self.latest_listings(card_id, variant)
        prices = [r.price for r in rows if r.price is not None]
        if not prices:
            return None
        return min(prices)

    def previous_listing_ids(self, card_id: str, variant: str) -> set[str]:
        """The listing_ids from the snapshot strictly older than the latest
        fetched_at (i.e. the prior fetch). Returns set() if there is no prior
        fetch — used by the T3 new-listing diff to find what dropped out.

        A "fetch" is identified by its DISTINCT fetched_at value: all rows
        sharing a fetched_at are one fetch (mirrors `latest_listings` and the
        spec's "rows from the newest fetched_at snapshot"). The latest row is
        resolved with `order_by(fetched_at.desc(), id.desc())` so the id
        tiebreak matches latest_graded's Windows-clock-tie discipline, but the
        fetched_at value is what defines the fetch group. The prior fetch is
        the rows with the second-newest distinct fetched_at.

        Known limitation: if two real fetches share the EXACT same fetched_at
        (Windows ~15ms clock tie between a baseline refresh and an immediate
        poll), they are indistinguishable from one merged multi-row fetch and
        are treated as a single "latest" snapshot — so `previous_listing_ids`
        returns the fetch BEFORE the tie (or set() if the tie is the only
        fetch). Splitting tied fetches requires a per-fetch id column
        (out of scope for T2's schema); T3 should ensure baseline and first
        poll land in distinct clock ticks (e.g. stamp fetched_at per-call, not
        per-row) if strict tied-fetch separation is required. See
        test_previous_listing_ids_tie_merges_same_timestamp_fetches.
        """
        # Latest row by (fetched_at desc, id desc) — the id tiebreak matches
        # latest_graded's discipline; we only consume the fetched_at value.
        latest_row = self.session.scalars(
            select(ListingSnapshot)
            .where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
            )
            .order_by(
                ListingSnapshot.fetched_at.desc(),
                ListingSnapshot.id.desc(),
            )
            .limit(1)
        ).first()
        if latest_row is None:
            return set()
        latest_fetched = latest_row.fetched_at
        # Prior fetch = the rows with the second-newest DISTINCT fetched_at.
        # `fetched_at < latest_fetched` selects everything strictly older; we
        # take the newest of those (again id-tiebroken for consistency) and
        # use its fetched_at as the prior fetch's stamp.
        prior_row = self.session.scalars(
            select(ListingSnapshot)
            .where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
                ListingSnapshot.fetched_at < latest_fetched,
            )
            .order_by(
                ListingSnapshot.fetched_at.desc(),
                ListingSnapshot.id.desc(),
            )
            .limit(1)
        ).first()
        if prior_row is None:
            return set()
        prior_fetched = prior_row.fetched_at
        rows = self.session.scalars(
            select(ListingSnapshot.listing_id).where(
                ListingSnapshot.card_id == card_id,
                ListingSnapshot.variant == variant,
                ListingSnapshot.fetched_at == prior_fetched,
            )
        ).all()
        return set(rows)