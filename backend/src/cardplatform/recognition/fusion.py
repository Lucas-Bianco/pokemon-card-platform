"""Combines the visual and OCR signals into one calibrated decision.

Why this exists, empirically: at a 2,993-card index, visual-only top-1 was 93.8% and
falling with scale, and every observed failure was a same-name/different-print pair
(Stunfisk ex -> Stunfisk ex, margin 0.006). The collector number resolves exactly those.

Meanwhile margin (top score minus runner-up) separates right from wrong: correct matches
averaged 0.081, incorrect ones 0.012. That is the signal `min_margin` thresholds on.

Defaults here are starting points. Task 11 calibrates them against real photographs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cardplatform.recognition.ocr import normalize_collector_number
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult


@dataclass(frozen=True)
class FusionConfig:
    # Below this top similarity, nothing plausible was found at all.
    min_similarity: float = 0.45
    # Above this margin the visual winner stands on its own.
    min_margin: float = 0.05
    # Confidence assigned when both signals agree.
    agreement_confidence: float = 0.97


def fuse(
    candidates: tuple[Candidate, ...],
    ocr: OcrReading,
    catalog_numbers: Mapping[str, str],
    config: FusionConfig | None = None,
) -> RecognitionResult:
    """Decide which candidate is the card, and how much to trust that.

    `catalog_numbers` maps each candidate's card_id to its collector number as printed
    in the catalog, so OCR can be checked against the shortlist.
    """
    config = config or FusionConfig()

    if not candidates:
        return RecognitionResult(
            card_id=None,
            confidence=0.0,
            status="not_found",
            candidates=(),
            ocr=ocr,
            visual_margin=0.0,
        )

    top = candidates[0]
    runner_up_score = candidates[1].visual_score if len(candidates) > 1 else 0.0
    margin = top.visual_score - runner_up_score

    if top.visual_score < config.min_similarity:
        return RecognitionResult(
            card_id=None,
            confidence=float(top.visual_score),
            status="not_found",
            candidates=candidates,
            ocr=ocr,
            visual_margin=margin,
        )

    # OCR arbitration: if the read number uniquely identifies one candidate, it wins
    # regardless of visual rank. This is the path that fixes same-artwork reprints.
    read_number = normalize_collector_number(ocr.collector_number)
    if read_number is not None:
        matches = [
            candidate
            for candidate in candidates
            if normalize_collector_number(catalog_numbers.get(candidate.card_id))
            == read_number
        ]
        if len(matches) == 1:
            return RecognitionResult(
                card_id=matches[0].card_id,
                confidence=config.agreement_confidence,
                status="confident",
                candidates=candidates,
                ocr=ocr,
                visual_margin=margin,
            )

    # No usable OCR: trust a clear visual winner, otherwise ask the user.
    if margin >= config.min_margin:
        return RecognitionResult(
            card_id=top.card_id,
            confidence=float(min(0.95, top.visual_score + margin)),
            status="confident",
            candidates=candidates,
            ocr=ocr,
            visual_margin=margin,
        )

    return RecognitionResult(
        card_id=None,
        confidence=float(top.visual_score),
        status="ambiguous",
        candidates=candidates,
        ocr=ocr,
        visual_margin=margin,
    )
