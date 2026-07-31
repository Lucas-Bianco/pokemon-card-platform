"""Orchestrates the recognition pipeline: rectify, embed, search, OCR, fuse."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Card
from cardplatform.grading.centering import CenteringResult, measure_centering
from cardplatform.recognition.detectors import detect_candidates
from cardplatform.recognition.fusion import FusionConfig, fuse
from cardplatform.recognition.rectify import rectify_from_corners
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

    def recognize(
        self,
        image: Image.Image,
        rectify: bool = True,
        corners: list[tuple[float, float]] | None = None,
    ) -> tuple[RecognitionResult, CenteringResult | None]:
        """Identify the card in `image`, and measure its centering.

        `rectify=False` is for callers that already rectified client-side (the Phase 1b
        PWA does this in WebAssembly for the live overlay).
        `corners` means the user placed them by hand — trust that over any detector.

        When detecting, every strategy's proposal is embedded and the best-matching crop
        wins. "Found a card-shaped quad" is not "found the card", and the strategies that
        recover the most frames are also the ones most able to return a plausible-looking
        crop of the wrong thing — so the arbiter is recognition itself, not detection
        confidence. Embedding costs 2.2 ms, so trying three is negligible; OCR costs
        about a second, so it runs only on the winner.
        """
        if not rectify:
            return self._recognize_crop(image)

        if corners is not None:
            crop = rectify_from_corners(
                image, np.array(corners, dtype="float32"), self.settings.rectified_size
            )
            return self._recognize_crop(crop)

        proposals = detect_candidates(image)
        if not proposals:
            logger.info("no card detected in frame by any strategy")
            # No crop was produced, so there is nothing to measure centering on.
            return (
                RecognitionResult(
                    card_id=None,
                    confidence=0.0,
                    status="not_found",
                    candidates=(),
                    ocr=OcrReading(),
                    visual_margin=0.0,
                ),
                None,
            )

        best_crop: Image.Image | None = None
        best_found: tuple = ()
        # -inf, not -1.0: a proposal whose search returns nothing scores -1.0, which
        # would fail to beat a -1.0 floor and leave the winning crop unset. A card was
        # still detected, so the crop it produced is what OCR must see.
        best_score = float("-inf")
        best_name = ""
        for name, quad in proposals:
            crop = rectify_from_corners(image, quad, self.settings.rectified_size)
            found = tuple(
                self.index.search(
                    self.encoder.embed(crop), top_k=self.settings.visual_top_k
                )
            )
            score = found[0].visual_score if found else -1.0
            if score > best_score:
                best_score, best_crop, best_found, best_name = score, crop, found, name

        logger.info(
            "detection strategy %r won with visual score %.3f", best_name, best_score
        )
        return self._fuse_for(best_crop, best_found)

    def _recognize_crop(
        self, crop: Image.Image
    ) -> tuple[RecognitionResult, CenteringResult | None]:
        found = tuple(
            self.index.search(self.encoder.embed(crop), top_k=self.settings.visual_top_k)
        )
        return self._fuse_for(crop, found)

    def _fuse_for(
        self, crop: Image.Image, found: tuple
    ) -> tuple[RecognitionResult, CenteringResult | None]:
        catalog_numbers = self._collector_numbers([c.card_id for c in found])
        # Drop index entries the catalog no longer knows about.
        candidates = tuple(c for c in found if c.card_id in catalog_numbers)

        if len(candidates) != len(found):
            # Should be unreachable: the index is built from the catalog and the loader
            # never deletes. Log loudly anyway — dropping the top candidate lets the
            # runner-up be scored against an empty field, which can turn a weak match
            # into a "confident" one. A stale index needs rebuilding, not tolerating.
            stale = [c.card_id for c in found if c.card_id not in catalog_numbers]
            logger.warning(
                "index returned %d card(s) absent from the catalog (%s); "
                "rebuild the index with 'cardplatform build-index'",
                len(stale),
                ", ".join(stale),
            )

        reading = self.reader.read(crop)
        result = fuse(candidates, reading, catalog_numbers, config=self.fusion_config)
        # Measured once, on the winning crop only — the losing proposals were never
        # the card, so measuring them would be pure waste.
        return result, measure_centering(crop)

    def _collector_numbers(self, card_ids: list[str]) -> dict[str, str]:
        if not card_ids:
            return {}
        rows = self.session.execute(
            select(Card.id, Card.number).where(Card.id.in_(card_ids))
        ).all()
        return {card_id: number for card_id, number in rows}
