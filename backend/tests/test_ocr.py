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


def test_parse_accepts_a_trailing_letter_suffix():
    """Real ids carry suffixes (63a, 12b). OCR read '63a/111' correctly on a real scan
    and the old pattern threw it away because it only allowed letters as a prefix."""
    assert parse_number_text("63a/111") == ("63A", "111")


def test_parse_still_accepts_a_prefix():
    assert parse_number_text("SV049/SV122") == ("SV049", "SV122")


def test_parse_still_rejects_free_text():
    """The suffix allowance must not turn the pattern into a general word matcher."""
    assert parse_number_text("weakness") == (None, None)
    assert parse_number_text("Illus. Mitsuhiro Arita") == (None, None)
    assert parse_number_text("Pokemon-GXrule") == (None, None)


def test_bare_suffix_number_is_accepted():
    assert parse_number_text("63a") == ("63A", None)


def test_wide_band_is_only_consulted_when_the_tight_strip_fails(monkeypatch):
    """The wide band contains rules text and copyright lines, so it is a fallback."""
    from PIL import Image

    from cardplatform.recognition.ocr import CollectorNumberReader

    reader = CollectorNumberReader()
    bands = []

    def fake_band(_self, _rectified, band):
        bands.append(band)
        return ("32/198",) if band[0] > 0.85 else ("nonsense",)

    monkeypatch.setattr(CollectorNumberReader, "_read_band", fake_band)
    reading = reader.read(Image.new("RGB", (600, 825)))

    assert reading.collector_number == "32"
    assert len(bands) == 1, "wide band should not be read when the tight strip succeeds"


def test_wide_band_accepts_only_a_full_reading(monkeypatch):
    """A bare number found in the wide band is usually an attack cost or a year.
    Measured: allowing bare reads there doubled wrong answers from 4 to 8."""
    from PIL import Image

    from cardplatform.recognition.ocr import CollectorNumberReader

    reader = CollectorNumberReader()

    def fake_band(_self, _rectified, band):
        return () if band[0] > 0.85 else ("20", "2016", "weakness")

    monkeypatch.setattr(CollectorNumberReader, "_read_band", fake_band)
    reading = reader.read(Image.new("RGB", (600, 825)))

    assert reading.collector_number is None
    assert "20" in reading.raw_regions


def test_wide_band_rescues_a_number_below_the_tight_strip(monkeypatch):
    from PIL import Image

    from cardplatform.recognition.ocr import CollectorNumberReader

    reader = CollectorNumberReader()

    def fake_band(_self, _rectified, band):
        return () if band[0] > 0.85 else ("weakness", "106/181")

    monkeypatch.setattr(CollectorNumberReader, "_read_band", fake_band)
    reading = reader.read(Image.new("RGB", (600, 825)))

    assert reading.collector_number == "106"
    assert reading.printed_total == "181"
