"""Orchestrates the recognition pipeline: rectify, embed, search, OCR, fuse."""

from __future__ import annotations

import copy
import dataclasses
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

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

    def recognize_many(
        self,
        image: Image.Image,
        quads: list[np.ndarray],
    ) -> list[tuple[np.ndarray, RecognitionResult, CenteringResult | None]]:
        """Recognize every quad in one image (Phase 4 bulk cataloger).

        Detection has already run (these are the N kept quads). Rectify each, embed
        them in ONE batched call, search the index per vector, then fuse + OCR each
        winning crop. OCR (~1 s/crop) is parallelized across a per-worker reader pool
        (RapidOCR is not thread-safe). Recognition is the arbiter: a quad that embeds
        low is a not_found per crop — geometry never auto-promotes.

        Returns one (quad, result, centering) per input quad, in input order.
        """
        if not quads:
            return []

        crops = [
            rectify_from_corners(image, quad, self.settings.rectified_size) for quad in quads
        ]
        vectors = self.encoder.embed_many(crops)
        found_per_crop = [
            tuple(self.index.search(vec, top_k=self.settings.visual_top_k))
            for vec in vectors
        ]

        workers = max(1, min(4, getattr(self.settings, "batch_ocr_workers", 1) or 1))
        # Each worker gets its own deep-copied reader (RapidOCR is not thread-safe).
        worker_readers = [copy.deepcopy(self.reader) for _ in range(workers)]

        results: list[tuple[np.ndarray, RecognitionResult, CenteringResult | None]] = [
            None  # type: ignore[list-item]
        ] * len(quads)

        if workers == 1 or len(quads) == 1:
            for i in range(len(quads)):
                result, centering = self._fuse_for(
                    crops[i], found_per_crop[i], reader=worker_readers[0]
                )
                results[i] = (quads[i], result, centering)
        else:
            def _job(i):
                return i, self._fuse_for(
                    crops[i], found_per_crop[i], reader=worker_readers[i % workers]
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                for i, (result, centering) in pool.map(_job, range(len(quads))):
                    results[i] = (quads[i], result, centering)
        return results

    def _recognize_crop(
        self, crop: Image.Image
    ) -> tuple[RecognitionResult, CenteringResult | None]:
        found = tuple(
            self.index.search(self.encoder.embed(crop), top_k=self.settings.visual_top_k)
        )
        return self._fuse_for(crop, found)

    def _fuse_for(
        self,
        crop: Image.Image,
        found: tuple,
        reader=None,
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

        # The worker pool passes its own per-worker reader so the shared self.reader
        # is never mutated across threads (RapidOCR is not thread-safe). The single-card
        # recognize path calls _fuse_for without a reader and uses self.reader.
        ocr_reader = reader if reader is not None else self.reader
        reading = ocr_reader.read(crop)
        result = fuse(candidates, reading, catalog_numbers, config=self.fusion_config)
        # The rectified crop is the canonical input Phase 3's grader needs, and the
        # only signal worth re-measuring centering on. Persist it once, here, on the
        # winning crop — the not_found path with no proposals returns before this and
        # keeps rectified_path=None. Fail-soft: a save error never breaks recognition.
        rectified_path = (
            self._persist_rectified_crop(crop) if result.status != "not_found" else None
        )
        result = dataclasses.replace(result, rectified_path=rectified_path)
        # Measured once, on the winning crop only — the losing proposals were never
        # the card, so measuring them would be pure waste.
        return result, measure_centering(crop)

    def _persist_rectified_crop(self, crop: Image.Image) -> str | None:
        """Write the rectified crop to the configured dir, returning its relative path.

        Returns None on any error so the caller can continue without a persisted crop
        rather than failing the scan. The relative path mirrors `scan_logs.image_path`'s
        `"scans/{name}"` convention so the same `data_dir / path` resolution works.
        """
        try:
            directory = self.settings.rectified_image_dir
            directory.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.png"
            crop.save(directory / name, "PNG")
            return f"rectified/{name}"
        except Exception:
            logger.warning("failed to persist rectified crop", exc_info=True)
            return None

    def _collector_numbers(self, card_ids: list[str]) -> dict[str, str]:
        if not card_ids:
            return {}
        rows = self.session.execute(
            select(Card.id, Card.number).where(Card.id.in_(card_ids))
        ).all()
        return {card_id: number for card_id, number in rows}
