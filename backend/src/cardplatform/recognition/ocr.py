"""Reads the collector number off a rectified card.

The collector number plus set is a unique key for a Pokemon card, which makes it an
extremely strong independent signal — and one that fails on completely different inputs
than visual embedding does.

Measured on a real rectified card (base1-4, 600x825): the number '4/102*' was read at
y 0.95-0.97, x 0.86 with confidence 0.90, while whole-card OCR cost 1.31 s. Cropping to
the bottom strip first is what keeps this interactive.
"""

from __future__ import annotations

import logging
import re

import numpy as np
from PIL import Image

from cardplatform.recognition.types import OcrReading

logger = logging.getLogger(__name__)

# Bottom strip of a rectified card, where the collector number is printed.
# Full width, not just the right side: vintage cards (base1) print the number bottom-right
# but every modern card (swsh, sv) prints it bottom-LEFT, so a right-only crop misses them
# entirely — measured, it read 1/4 reference cards instead of 3/4.
_NUMBER_REGION = (0.0, 0.88, 1.0, 1.0)  # left, top, right, bottom as fractions

_NUMBER_PATTERN = re.compile(r"([A-Z]{0,3}\d{1,4})\s*/\s*([A-Z]{0,3}\d{1,4})")
_BARE_NUMBER_PATTERN = re.compile(r"^([A-Z]{0,3}\d{1,4})$")


def parse_number_text(text: str) -> tuple[str | None, str | None]:
    """Extract (collector_number, printed_total) from an OCR fragment."""
    if not text:
        return (None, None)
    cleaned = text.strip().upper().replace(" ", "")

    match = _NUMBER_PATTERN.search(cleaned)
    if match:
        return (match.group(1), match.group(2))

    bare = _BARE_NUMBER_PATTERN.match(cleaned)
    if bare:
        return (bare.group(1), None)
    return (None, None)


def normalize_collector_number(number: str | None) -> str | None:
    """Canonical form for comparison against the catalog.

    The catalog stores '4' where a card prints '004', and 'SV49' where OCR may read
    'SV049', so leading zeros are stripped from the numeric part only.
    """
    if number is None:
        return None
    cleaned = number.strip().upper()
    match = re.match(r"^([A-Z]*)(\d+)$", cleaned)
    if not match:
        return cleaned
    prefix, digits = match.groups()
    return f"{prefix}{int(digits)}"


def select_number_region(regions: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Pick the collector number out of every text fragment OCR found in the strip.

    The full-width strip also contains flavour text, retreat cost, and the copyright
    line, so 'first fragment that parses' is not good enough: on hgss4-1 that picked the
    retreat-cost '20'. A fragment in printed 'N/M' form is far stronger evidence than a
    bare number, so all fragments are checked for that form before falling back.
    """
    for text in regions:
        number, total = parse_number_text(text)
        if number is not None and total is not None:
            return (number, total)
    for text in regions:
        number, total = parse_number_text(text)
        if number is not None:
            return (number, total)
    return (None, None)


class CollectorNumberReader:
    def __init__(self) -> None:
        self._engine = None  # loaded lazily; construction is expensive

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read(self, rectified: Image.Image) -> OcrReading:
        """OCR the number region of a rectified card. Never raises."""
        width, height = rectified.size
        left, top, right, bottom = _NUMBER_REGION
        crop = rectified.crop(
            (int(width * left), int(height * top), int(width * right), int(height * bottom))
        )
        # Upscale: the number is small, and OCR accuracy improves markedly with size.
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)

        try:
            results, _ = self._get_engine()(np.array(crop))
        except Exception as exc:  # noqa: BLE001 - OCR engines raise broadly
            logger.warning("ocr failed: %s", exc)
            return OcrReading()

        if not results:
            return OcrReading()

        regions = tuple(str(text) for _, text, _ in results)
        number, total = select_number_region(regions)
        return OcrReading(
            collector_number=number, printed_total=total, raw_regions=regions
        )
