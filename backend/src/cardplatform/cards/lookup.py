"""Search cards by name and attach each match's latest market price.

The 'Prices' tab's type-a-name -> see-the-price flow: a flat list of matching
cards, each carrying its current market figure (or an honest null when no
snapshot exists). Mirrors the existing name-search pattern in api.search_cards
(func.lower().like(), NOT ilike) and reuses PriceService.latest_price so the
notion of 'the price' matches the rest of the app.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card
from cardplatform.prices.service import PriceService


class CardLookupService:
    def __init__(self, session: Session, price_service: PriceService) -> None:
        self.session = session
        self.price_service = price_service

    def lookup(self, q: str, limit: int = 20) -> list[dict]:
        q = (q or "").strip().lower()
        # Defensive: the route 422s on too-short, but the service is safe to call
        # directly (e.g. from another service) and must not return matches for
        # a blank or single-char query.
        if len(q) < 2:
            return []

        pattern = f"%{q}%"
        cards = self.session.scalars(
            select(Card)
            .where(func.lower(Card.name).like(pattern))
            .order_by(Card.name, Card.id)
            .limit(limit)
        ).all()

        results: list[dict] = []
        for card in cards:
            snapshot = self.price_service.latest_price(card.id, "normal")
            # market is NEVER 0 by fabrication: a missing snapshot is honestly None.
            market = snapshot.market if snapshot is not None else None
            source = snapshot.source if snapshot is not None else None
            # source_updated_at uses the "" sentinel for missing stamps (see
            # PriceSnapshot); `or None` mirrors completion.set_detail's wire
            # behavior so the UI never shows "" where it means "no timestamp".
            source_updated_at = (
                snapshot.source_updated_at or None if snapshot is not None else None
            )

            results.append(
                {
                    "card_id": card.id,
                    "name": card.name,
                    "set_id": card.set_id,
                    "set_name": card.card_set.name,
                    "number": card.number,
                    "rarity": card.rarity,
                    "image_small": card.image_small,
                    "image_large": card.image_large,
                    "market": market,
                    "source": source,
                    "source_updated_at": source_updated_at,
                }
            )
        return results