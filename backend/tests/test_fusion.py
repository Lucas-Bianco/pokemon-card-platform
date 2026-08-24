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
    Visual alone picks wrong; the collector number settles it.

    The reading carries `printed_total`, because only a full 'N/M' read is trusted
    enough to override visual rank.
    """
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(
        candidates,
        OcrReading(collector_number="114", printed_total="252"),
        numbers_for(["me2pt5-252", "me2pt5-114"]),
    )

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_full_reading_promotes_a_lower_ranked_candidate():
    """A complete 'N/M' read is strong enough to outrank the visual winner."""
    candidates = (Candidate("ex3-88", 0.79), Candidate("ex15-82", 0.78))

    result = fuse(
        candidates,
        OcrReading(collector_number="82", printed_total="115"),
        numbers_for(["ex3-88", "ex15-82"]),
    )

    assert result.card_id == "ex15-82"
    assert result.status == "confident"


def test_bare_reading_does_not_promote_a_non_top_candidate():
    """Regression guard for the measured hgss4-1 misread.

    That card prints '1/102'; OCR dropped the leading digit and returned a bare '102'
    with no total. If a bare number were allowed to promote, that misread would override
    a correct visual top-1 and return it as `confident` — a confidently wrong answer.
    """
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(
        candidates,
        OcrReading(collector_number="4", printed_total=None),
        {"base1-4": "17", "base4-4": "4"},
    )

    assert result.card_id == "base1-4"
    assert result.status == "confident"


def test_bare_reading_confirming_the_visual_winner_is_agreement():
    """A bare number may still confirm what vision already chose."""
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))
    config = FusionConfig()

    result = fuse(
        candidates,
        OcrReading(collector_number="004", printed_total=None),
        {"base1-4": "4", "base4-4": "17"},
    )

    assert result.card_id == "base1-4"
    assert result.status == "confident"
    assert result.confidence == pytest.approx(config.agreement_confidence)


def test_bare_reading_on_a_narrow_margin_stays_ambiguous():
    """Discarding a bare disagreement must not manufacture a decision either way."""
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(
        candidates,
        OcrReading(collector_number="114", printed_total=None),
        numbers_for(["me2pt5-252", "me2pt5-114"]),
    )

    assert result.status == "ambiguous"
    assert result.card_id is None


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


def test_promo_code_promotes_a_lower_ranked_candidate():
    """A letter-prefixed promo code is strong evidence, like a full 'N/M' read.

    Measured 2026-08-22 over the 109 saved scans: promos are penalised twice — they
    look like other promos visually, and their numbers carry no '/M' denominator, so
    under the old rule OCR could only ever confirm the visual top-1, never correct it.
    Scan 59 read 'SM102' correctly against a wrong visual winner and had to decline.

    The prefix does the same evidentiary job the '/' does: it proves OCR located the
    collector-number field rather than lifting an HP value, a retreat cost, or a
    copyright year. Uniqueness across the shortlist is still required.
    """
    candidates = (Candidate("smp-SM68", 0.79), Candidate("smp-SM102", 0.78))

    result = fuse(
        candidates,
        OcrReading(collector_number="SM102", printed_total=None),
        {"smp-SM68": "SM68", "smp-SM102": "SM102"},
    )

    assert result.card_id == "smp-SM102"
    assert result.status == "confident"


def test_bare_digits_still_cannot_promote_after_the_promo_change():
    """The hgss4-1 guard must survive: digits alone remain confirm-only.

    This is the invariant the promo change must NOT weaken — a bare '102' misread
    from '1/102' still may not override a correct visual winner.
    """
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(
        candidates,
        OcrReading(collector_number="102", printed_total=None),
        {"base1-4": "17", "base4-4": "102"},
    )

    assert result.card_id == "base1-4"
    assert result.status == "confident"


def test_promo_code_matching_two_candidates_does_not_decide():
    """Ambiguous evidence decides nothing, prefix or not."""
    candidates = (Candidate("smp-SM68", 0.79), Candidate("other-SM68", 0.785))

    result = fuse(
        candidates,
        OcrReading(collector_number="SM68", printed_total=None),
        {"smp-SM68": "SM68", "other-SM68": "SM68"},
    )

    assert result.status == "ambiguous"
    assert result.card_id is None
