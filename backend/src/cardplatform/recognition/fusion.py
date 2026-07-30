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
    # Above this margin the visual winner stands on its own, with no OCR backup.
    #
    # Calibrated 2026-07-29 over 3,000 queries (500 cards x 6 degradations) against the
    # full 20,391-card index. Margin separates correct from incorrect matches 13.7x
    # (0.1201 vs 0.0088). Measured precision on auto-confirmed matches:
    #
    #     0.02 -> 89.9% auto, 99.5% precision, 14 wrong
    #     0.05 -> 78.8% auto, 100.0% precision,  1 wrong
    #     0.06 -> 74.6% auto, 100.0% precision,  0 wrong
    #
    # The harness recommends 0.02 as the lowest threshold clearing 99%, but that is the
    # wrong trade here: a confidently wrong identification is far worse for this product
    # than one extra "which of these three?" prompt, and 14 wrong in 3,000 is not a rate
    # worth 11 percentage points of extra auto-confirm. 0.05 buys near-perfect precision
    # while still auto-confirming four scans in five. Note this threshold only decides
    # cases OCR could not arbitrate, so it is a fallback path, not the common one.
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

    # OCR arbitration: if the read number uniquely identifies one candidate, it can
    # decide. This is the path that fixes same-artwork reprints.
    #
    # Trust is deliberately asymmetric, and must stay that way. A reading that captured
    # the full 'N/M' form is much stronger evidence than a bare number, because the '/'
    # is what proves OCR located the collector-number field at all rather than picking up
    # a retreat cost, an HP value, or a copyright year. Measured: hgss4-1 prints '1/102',
    # OCR dropped the leading digit and returned a bare '102' with no total. Given equal
    # authority, that misread would promote whichever shortlisted card happens to be
    # number 102 over a correct visual top-1 — turning a right answer into a confidently
    # wrong one, the worst outcome this pipeline can produce. So:
    #   full 'N/M'  -> may override visual rank (promote a lower-ranked candidate)
    #   bare number -> may only confirm the visual top-1, never promote
    read_number = normalize_collector_number(ocr.collector_number)
    if read_number is not None:
        matches = [
            candidate
            for candidate in candidates
            if normalize_collector_number(catalog_numbers.get(candidate.card_id))
            == read_number
        ]
        if len(matches) == 1:
            matched = matches[0]
            captured_full_form = ocr.printed_total is not None
            if captured_full_form or matched.card_id == top.card_id:
                return RecognitionResult(
                    card_id=matched.card_id,
                    confidence=config.agreement_confidence,
                    status="confident",
                    candidates=candidates,
                    ocr=ocr,
                    visual_margin=margin,
                )
            # A bare reading disagreeing with visual rank is too weak to act on at all,
            # so it is discarded and the decision falls through to the margin logic.

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
