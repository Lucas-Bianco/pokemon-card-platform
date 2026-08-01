"""Writes price snapshots and answers latest-price queries.

Snapshots are immutable and deduplicated on the source's own updatedAt stamp, so
re-running a refresh does not inflate history with identical rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cardplatform.db.models import PriceSnapshot
from cardplatform.prices.provider import PriceProvider


class PriceService:
    def __init__(self, session: Session, provider: PriceProvider | None = None) -> None:
        # provider is optional so read-only consumers (e.g. collection valuation) can
        # construct the service just for latest_price without wiring up a fetcher.
        self.session = session
        self.provider = provider

    def refresh_card(self, card_id: str) -> int:
        """Fetch and persist new snapshots. Returns the number of rows written."""
        if self.provider is None:
            raise RuntimeError(
                "PriceService was constructed without a provider; refresh_card is unavailable"
            )
        written = 0
        for quote in self.provider.fetch(card_id):
            stamp = quote.source_updated_at or ""
            if self._already_recorded(quote.card_id, quote.source, quote.variant, stamp):
                continue
            self.session.add(
                PriceSnapshot(
                    card_id=quote.card_id,
                    source=quote.source,
                    variant=quote.variant,
                    low=quote.low,
                    mid=quote.mid,
                    high=quote.high,
                    market=quote.market,
                    source_updated_at=stamp,
                )
            )
            written += 1
        self.session.commit()
        return written

    def latest_price(self, card_id: str, variant: str) -> PriceSnapshot | None:
        """Newest tcgplayer snapshot for this exact variant, else the cardmarket aggregate.

        tcgplayer prices per printing variant; cardmarket only publishes one aggregate
        figure per card. They never share a variant value, so an explicit fallback is
        required — a source-priority sort over a single result set can never fire.
        """
        return self._newest(card_id, "tcgplayer", variant) or self._newest(
            card_id, "cardmarket", "aggregate"
        )

    def price_history(
        self,
        card_id: str,
        variant: str,
        since: datetime | None = None,
        days: int | None = None,
    ) -> list[PriceSnapshot]:
        """One point per source_updated_at, tcgplayer-preferred, oldest first.

        Mirrors latest_price's tcgplayer-then-cardmarket/aggregate resolution per date,
        so a chart shows the same notion of 'the price' the rest of the app uses, while
        never blending sources: each returned point carries its own source and
        source_updated_at. When both sources share a date, tcgplayer wins; cardmarket-only
        dates remain as their own points.

        Ordered by fetched_at (the indexed observation time). source_updated_at is a
        free-text stamp whose format differs between providers, so it sorts reliably only
        within one source — not across the mixed series a chart needs.
        """
        if since is None and days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = select(PriceSnapshot).where(
            PriceSnapshot.card_id == card_id,
            or_(
                (PriceSnapshot.source == "tcgplayer") & (PriceSnapshot.variant == variant),
                (PriceSnapshot.source == "cardmarket") & (PriceSnapshot.variant == "aggregate"),
            ),
        )
        if since is not None:
            stmt = stmt.where(PriceSnapshot.fetched_at >= since)
        stmt = stmt.order_by(PriceSnapshot.fetched_at.asc(), PriceSnapshot.id.asc())

        rows = self.session.scalars(stmt).all()

        # Collapse to one point per source_updated_at, tcgplayer preferred. Rows arrive
        # oldest-fetched first; the first row seen for a date claims its slot, and a
        # tcgplayer row later displaces a cardmarket row for the same date (never the
        # reverse). dict insertion order keeps the result ascending by first observation.
        by_date: dict[str, PriceSnapshot] = {}
        for row in rows:
            date = row.source_updated_at
            existing = by_date.get(date)
            if existing is None:
                by_date[date] = row
            elif row.source == "tcgplayer" and existing.source != "tcgplayer":
                by_date[date] = row
        return list(by_date.values())

    def _newest(self, card_id: str, source: str, variant: str) -> PriceSnapshot | None:
        return self.session.scalars(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.source == source,
                PriceSnapshot.variant == variant,
            )
            # id breaks fetched_at ties: _utcnow() is evaluated per row in a single
            # flush, and Windows clock granularity (~15ms) produces real ties.
            .order_by(PriceSnapshot.fetched_at.desc(), PriceSnapshot.id.desc())
            .limit(1)
        ).first()

    def _already_recorded(
        self, card_id: str, source: str, variant: str, source_updated_at: str
    ) -> bool:
        existing = self.session.scalars(
            select(PriceSnapshot).where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.source == source,
                PriceSnapshot.variant == variant,
                PriceSnapshot.source_updated_at == source_updated_at,
            )
        ).first()
        return existing is not None
