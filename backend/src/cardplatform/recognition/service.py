"""Orchestrates the recognition pipeline: rectify, embed, search, OCR, fuse."""

from __future__ import annotations

import logging

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Card
from cardplatform.recognition.fusion import FusionConfig, fuse
from cardplatform.recognition.rectify import rectify_card
from cardplatform.recognition.types import OcrReading, RecognitionResult

logger = logging.getLogger(__name__)


class RecognitionService:
    def __init__(
        self,
        session: Session,
        encoder,
        index,
        reader,
        settings: Settings | None = None,
        fusion_config: FusionConfig | None = None,
    ) -> None:
        self.session = session
        self.encoder = encoder
        self.index = index
        self.reader = reader
        self.settings = settings or default_settings
        self.fusion_config = fusion_config

    def recognize(self, image: Image.Image, rectify: bool = True) -> RecognitionResult:
        """Identify the card in `image`.

        `rectify=False` is for callers that already rectified client-side (the Phase 1b
        PWA does this in WebAssembly for the live overlay).
        """
        working = image
        if rectify:
            flattened = rectify_card(image, size=self.settings.rectified_size)
            if flattened is None:
                logger.info("no card detected in frame")
                return RecognitionResult(
                    card_id=None,
                    confidence=0.0,
                    status="not_found",
                    candidates=(),
                    ocr=OcrReading(),
                    visual_margin=0.0,
                )
            working = flattened

        vector = self.encoder.embed(working)
        raw_candidates = self.index.search(vector, top_k=self.settings.visual_top_k)

        catalog_numbers = self._collector_numbers([c.card_id for c in raw_candidates])
        # Drop index entries the catalog no longer knows about.
        candidates = tuple(c for c in raw_candidates if c.card_id in catalog_numbers)

        if len(candidates) != len(raw_candidates):
            # Should be unreachable: the index is built from the catalog and the loader
            # never deletes. Log loudly anyway — dropping the top candidate lets the
            # runner-up be scored against an empty field, which can turn a weak match
            # into a "confident" one. A stale index needs rebuilding, not tolerating.
            stale = [c.card_id for c in raw_candidates if c.card_id not in catalog_numbers]
            logger.warning(
                "index returned %d card(s) absent from the catalog (%s); "
                "rebuild the index with 'cardplatform build-index'",
                len(stale),
                ", ".join(stale),
            )

        reading = self.reader.read(working)
        return fuse(candidates, reading, catalog_numbers, config=self.fusion_config)

    def _collector_numbers(self, card_ids: list[str]) -> dict[str, str]:
        if not card_ids:
            return {}
        rows = self.session.execute(
            select(Card.id, Card.number).where(Card.id.in_(card_ids))
        ).all()
        return {card_id: number for card_id, number in rows}
