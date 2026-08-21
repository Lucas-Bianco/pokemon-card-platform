"""Tests for the honest catalog-consistency authenticity check.

The only authenticity signal this dataset supports is a cross-check between
what OCR read off the card (the printed collector number) and what the
recognition pipeline matched it to (the catalog card's canonical number). A
mismatch is NOT a counterfeit verdict — it is equally likely a wrong
recognition, and the project has zero confirmed-counterfeit samples to
calibrate against. These tests pin that honest behaviour.

Normalization is the load-bearing piece: OCR sees "080", "080/165", " 080 ";
the catalog stores "80" or "080". They must all compare equal.
"""

from cardplatform.authenticity.consistency import (
    ConsistencyResult,
    _normalize,
    check_consistency,
)
from cardplatform.authenticity.checklist import checklist_for


# --- normalization -----------------------------------------------------------


def test_normalize_strips_leading_zeros():
    assert _normalize("080") == "80"
    assert _normalize("80") == "80"


def test_normalize_strips_trailing_denominator():
    # Cards print "43/165" (collector number / set size); the denominator is not
    # part of the number and must not survive normalization.
    assert _normalize("080/165") == "80"
    assert _normalize("43 / 99") == "43"


def test_normalize_strips_surrounding_whitespace():
    assert _normalize("  080  ") == "80"


def test_normalize_all_zeros_collapses_to_zero():
    assert _normalize("000") == "0"


def test_normalize_empty_or_nondigit_yields_none():
    assert _normalize("") is None
    assert _normalize(None) is None
    assert _normalize("abc") is None
    assert _normalize("  ") is None


def test_normalize_keeps_only_digits():
    # OCR sometimes reads "No.080" or "SV080"; only the digits matter.
    assert _normalize("No.080") == "80"
    assert _normalize("SV080") == "80"


# --- check_consistency ------------------------------------------------------


def test_match_when_ocr_equals_catalog_after_normalization():
    r = check_consistency("080", "80", card_id="sv9-80", card_name="Sprigatito")
    assert r.match == "match"
    assert r.printed_number == "80"
    assert r.catalog_number == "80"
    assert r.card_id == "sv9-80"
    assert "Sprigatito" in r.note


def test_mismatch_when_ocr_differs_from_catalog():
    # The real case from the baseline: scan matched sv9-35 but OCR read "043".
    r = check_consistency("043", "35", card_id="sv9-35", card_name="Some Card")
    assert r.match == "mismatch"
    assert r.printed_number == "43"
    assert r.catalog_number == "35"
    # The honest ambiguity must be surfaced, not a counterfeit verdict.
    assert "recognition was wrong" in r.note
    assert "counterfeit" in r.note.lower()
    assert "cannot tell" in r.note.lower()


def test_unread_when_ocr_is_none_but_card_matched():
    r = check_consistency(None, "35", card_id="sv9-35", card_name="Some Card")
    assert r.match == "unread"
    assert r.printed_number is None
    assert r.catalog_number == "35"
    assert "could not read" in r.note.lower()


def test_no_card_when_card_id_is_none():
    # A not_found scan: no card matched, so there is no catalog number to check.
    r = check_consistency("080", None, card_id=None, card_name=None)
    assert r.match == "no_card"
    assert r.catalog_number is None
    assert "no card was recognized" in r.note.lower()


def test_no_card_wins_over_unread():
    # No card AND no OCR: the no-card explanation is the honest one (there is
    # nothing to compare against), not "couldn't read".
    r = check_consistency(None, None, card_id=None, card_name=None)
    assert r.match == "no_card"


def test_result_is_frozen():
    r = check_consistency("080", "80", card_id="sv9-80", card_name="X")
    import dataclasses

    assert dataclasses.is_dataclass(r)
    try:
        r.match = "mismatch"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ConsistencyResult must be frozen")


# --- checklist ---------------------------------------------------------------


def test_checklist_returns_items():
    items = checklist_for(rarity="Common", variant=None)
    assert len(items) >= 4
    ids = {i.id for i in items}
    assert "rosette" in ids
    assert "edge_layering" in ids


def test_checklist_holo_item_applies_only_for_holo_rarity():
    holo = checklist_for(rarity="Rare Holo", variant=None)
    common = checklist_for(rarity="Common", variant=None)
    none = checklist_for(rarity=None, variant=None)

    holo_light_holo = next(i for i in holo if i.id == "holo_light")
    holo_light_common = next(i for i in common if i.id == "holo_light")
    holo_light_none = next(i for i in none if i.id == "holo_light")

    assert holo_light_holo.applies is True
    assert holo_light_common.applies is False
    assert holo_light_none.applies is False


def test_checklist_non_holo_items_always_apply():
    for rarity in ("Common", "Rare Holo", None):
        items = checklist_for(rarity=rarity, variant=None)
        rosette = next(i for i in items if i.id == "rosette")
        assert rosette.applies is True


def test_checklist_items_have_honest_caveats():
    items = checklist_for(rarity="Rare Holo", variant=None)
    for item in items:
        assert item.title
        assert item.what_to_check
        assert item.caveat  # every check carries an honest limitation