"""Writes graded-price snapshots and answers latest-graded-price queries.

Mirrors PriceService: snapshots are immutable and deduplicated on the source's
own freshness stamp (source_updated_at), so re-running a refresh does not
inflate history with identical rows. The empty-string sentinel for a missing
stamp matches GradedPriceSnapshot's unique constraint (see models.py).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import GradedPriceSnapshot
from cardplatform.prices.graded_provider import GradedPriceProvider


class GradedPriceService:
    def __init__(self, session: Session, provider: GradedPriceProvider | None = None) -> None:
        # provider is optional so read-only consumers (e.g. the grading-upside
        # endpoint in T5) can construct the service just for latest_graded
        # without wiring up a fetcher.
        self.session = session
        self.provider = provider

    def refresh_graded(self, card_id: str) -> int:
        """Fetch and persist new graded snapshots. Returns the number of rows written.

        Returns 0 (NOT an error) when the provider returns [] — that is the
        honest "graded prices unavailable" state (no API key, 404 on an
        unrecognized id, transport failure after retries). Only raises when the
        service itself was constructed without a provider, mirroring
        PriceService.refresh_card.
        """
        if self.provider is None:
            raise RuntimeError(
                "GradedPriceService was constructed without a provider; "
                "refresh_graded is unavailable"
            )
        written = 0
        for quote in self.provider.fetch_graded(card_id):
            stamp = quote.source_updated_at or ""
            if self._already_recorded_graded(
                quote.card_id, quote.grader, quote.grade, quote.variant, stamp
            ):
                continue
            self.session.add(
                GradedPriceSnapshot(
                    card_id=quote.card_id,
                    grader=quote.grader,
                    grade=quote.grade,
                    variant=quote.variant,
                    low=quote.low,
                    mid=quote.mid,
                    high=quote.high,
                    market=quote.market,
                    source=quote.source,
                    source_updated_at=stamp,
                )
            )
            written += 1
        self.session.commit()
        return written

    def latest_graded(
        self,
        card_id: str,
        variant: str,
        grade: float,
        grader: str = "PSA",
    ) -> GradedPriceSnapshot | None:
        """Newest snapshot for the exact (card_id, variant, grade, grader) tuple.

        Ordered by fetched_at desc then id desc — id breaks fetched_at ties
        because _utcnow() is evaluated per row in a single flush and Windows
        clock granularity (~15ms) produces real ties (mirrors PriceService._newest).
        """
        return self.session.scalars(
            select(GradedPriceSnapshot)
            .where(
                GradedPriceSnapshot.card_id == card_id,
                GradedPriceSnapshot.variant == variant,
                GradedPriceSnapshot.grade == grade,
                GradedPriceSnapshot.grader == grader,
            )
            .order_by(
                GradedPriceSnapshot.fetched_at.desc(),
                GradedPriceSnapshot.id.desc(),
            )
            .limit(1)
        ).first()

    def _already_recorded_graded(
        self,
        card_id: str,
        grader: str,
        grade: float,
        variant: str,
        source_updated_at: str,
    ) -> bool:
        existing = self.session.scalars(
            select(GradedPriceSnapshot).where(
                GradedPriceSnapshot.card_id == card_id,
                GradedPriceSnapshot.grader == grader,
                GradedPriceSnapshot.grade == grade,
                GradedPriceSnapshot.variant == variant,
                GradedPriceSnapshot.source_updated_at == source_updated_at,
            )
        ).first()
        return existing is not None