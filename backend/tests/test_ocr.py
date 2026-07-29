import pytest

from cardplatform.recognition.ocr import (
    CollectorNumberReader,
    normalize_collector_number,
    parse_number_text,
    select_number_region,
)


def test_parse_number_text_splits_number_and_total():
    assert parse_number_text("4/102") == ("4", "102")


def test_parse_number_text_tolerates_trailing_symbols():
    """Real OCR of base1-4 returned '4/102*' — the rarity glyph bleeds in."""
    assert parse_number_text("4/102*") == ("4", "102")


def test_parse_number_text_handles_promo_style_numbers():
    assert parse_number_text("SV049/SV122") == ("SV049", "SV122")


def test_parse_number_text_rejects_non_numbers():
    assert parse_number_text("Charizard") == (None, None)
    assert parse_number_text("") == (None, None)


def test_parse_number_text_handles_missing_total():
    assert parse_number_text("179") == ("179", None)


def test_normalize_strips_leading_zeros_for_matching():
    assert normalize_collector_number("004") == "4"
    assert normalize_collector_number("SV049") == "SV49"
    assert normalize_collector_number(None) is None


def test_normalize_is_idempotent():
    assert normalize_collector_number(normalize_collector_number("004")) == "4"


@pytest.mark.parametrize("junk", ["", "   ", "|||"])
def test_parse_handles_ocr_junk(junk):
    assert parse_number_text(junk) == (None, None)


def test_select_prefers_printed_total_over_a_bare_number():
    """Real regions from hgss4-1: the retreat cost '20' precedes the collector number.
    Taking the first fragment that parses read '20' as the card number."""
    regions = ("weakness", "retreatcost", "20", "C2010Pokemon", "1/102")

    assert select_number_region(regions) == ("1", "102")


def test_select_falls_back_to_a_bare_number():
    assert select_number_region(("Illus. Arita", "179")) == ("179", None)


def test_select_returns_nothing_when_no_fragment_is_a_number():
    assert select_number_region(("Illus. Arita", "GAMEFREAK")) == (None, None)
    assert select_number_region(()) == (None, None)


def test_reader_returns_empty_reading_for_blank_image():
    from PIL import Image

    reading = CollectorNumberReader().read(Image.new("RGB", (600, 825), (255, 255, 255)))

    assert reading.collector_number is None
    assert reading.raw_regions == ()
