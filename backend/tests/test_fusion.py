import pytest

from cardplatform.recognition.fusion import FusionConfig, fuse
from cardplatform.recognition.types import Candidate, OcrReading

# card_id -> collector number, as the catalog knows it
CATALOG = {
    "base1-4": "4",
    "base4-4": "4",
    "me2pt5-114": "114",
    "me2pt5-252": "252",
    "ex15-82": "82",
    "ex3-88": "88",
}


def numbers_for(card_ids):
    return {cid: CATALOG[cid] for cid in card_ids if cid in CATALOG}


def test_clear_visual_winner_with_ocr_agreement_is_confident():
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(
        candidates,
        OcrReading(collector_number="4", printed_total="102"),
        numbers_for(["base1-4", "base4-4"]),
    )

    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.confidence > 0.9


def test_ocr_breaks_a_visual_tie():
    """The measured real failure: same name, different print, margin 0.006.
    Visual alone picks wrong; the collector number settles it."""
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(
        candidates,
        OcrReading(collector_number="114"),
        numbers_for(["me2pt5-252", "me2pt5-114"]),
    )

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_ocr_promotes_a_lower_ranked_candidate():
    candidates = (Candidate("ex3-88", 0.79), Candidate("ex15-82", 0.78))

    result = fuse(candidates, OcrReading(collector_number="82"), numbers_for(["ex3-88", "ex15-82"]))

    assert result.card_id == "ex15-82"


def test_narrow_margin_without_ocr_is_ambiguous():
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(candidates, OcrReading(), numbers_for(["me2pt5-252", "me2pt5-114"]))

    assert result.status == "ambiguous"
    assert result.card_id is None
    assert len(result.candidates) == 2


def test_ocr_matching_nothing_falls_back_to_visual():
    """A misread number must not veto a confident visual match."""
    candidates = (Candidate("base1-4", 0.91), Candidate("base4-4", 0.60))

    result = fuse(
        candidates,
        OcrReading(collector_number="999"),
        numbers_for(["base1-4", "base4-4"]),
    )

    assert result.card_id == "base1-4"
    assert result.status == "confident"


def test_low_similarity_is_not_found():
    candidates = (Candidate("base1-4", 0.31), Candidate("base4-4", 0.29))

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]))

    assert result.status == "not_found"
    assert result.card_id is None


def test_no_candidates_is_not_found():
    result = fuse((), OcrReading(), {})

    assert result.status == "not_found"
    assert result.candidates == ()
    assert result.confidence == 0.0


def test_ambiguous_ocr_match_does_not_decide():
    """Two candidates sharing a collector number: OCR cannot disambiguate."""
    candidates = (Candidate("base1-4", 0.70), Candidate("base4-4", 0.69))

    result = fuse(
        candidates, OcrReading(collector_number="004"), {"base1-4": "4", "base4-4": "4"}
    )

    assert result.status == "ambiguous"


def test_visual_margin_is_reported():
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]))

    assert result.visual_margin == pytest.approx(0.27, abs=1e-6)


def test_thresholds_are_configurable():
    candidates = (Candidate("base1-4", 0.60), Candidate("base4-4", 0.50))
    strict = FusionConfig(min_similarity=0.85)

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]), config=strict)

    assert result.status == "not_found"


def test_single_candidate_has_full_margin():
    """With nothing to compare against, the runner-up score is treated as 0."""
    result = fuse((Candidate("base1-4", 0.80),), OcrReading(), {"base1-4": "4"})

    assert result.status == "confident"
    assert result.card_id == "base1-4"
