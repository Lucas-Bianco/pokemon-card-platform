"""Writes price snapshots and answers latest-price queries.

Snapshots are immutable and deduplicated on the source's own updatedAt stamp, so
re-running a refresh does not inflate history with identical rows.
"""

from __future__ import annotations

from sqlalchemy import select
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

    def _newest(self, card_id: str, source: str, variant: str) -> PriceSnapshot | None:
        return self.session.scalars(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.source == source,
                PriceSnapshot.variant == variant,
            )
            .order_by(PriceSnapshot.fetched_at.desc())
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
