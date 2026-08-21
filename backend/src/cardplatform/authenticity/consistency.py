"""The one honest authenticity signal: printed number vs catalog number.

OCR reads the collector number printed on the card; the recognition pipeline
matches the card to a catalog entry that carries its own canonical number. The
cross-check between the two is the only authenticity signal this dataset
supports without fabricating one.

A mismatch is deliberately NOT a counterfeit verdict. It is equally likely a
wrong recognition (the visual matcher picked the wrong card, and the printed
number is the truthful evidence of that), and the project has zero
confirmed-counterfeit samples to calibrate against — so the honest surface is
"the recognition was wrong OR the card is a counterfeit, the app cannot tell
which." Anything stronger would be theater.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MatchStatus = Literal["match", "mismatch", "unread", "no_card"]


@dataclass(frozen=True)
class ConsistencyResult:
    """The result of comparing the printed number to the catalog number.

    ``printed_number`` and ``catalog_number`` are normalized (leading zeros and
    denominators stripped); ``None`` means that side could not be produced — a
    scan that named no card has ``catalog_number is None``, and a scan whose OCR
    read nothing has ``printed_number is None``. ``note`` is the honest
    explanation surfaced to the user, never a verdict.
    """

    printed_number: str | None
    catalog_number: str | None
    card_id: str | None
    card_name: str | None
    match: MatchStatus
    note: str


# A trailing "/165" set-size denominator (optionally surrounded by spaces) is
# printed on many cards and is not part of the collector number.
_DENOM_RE = re.compile(r"\s*/\s*\d+\s*$")
# Keep digits only: OCR often reads "No.080" or "SV080" or inserts spaces.
_NONDIGIT_RE = re.compile(r"[^0-9]")


def _normalize(raw: str | None) -> str | None:
    """Normalize a collector number to bare digits with leading zeros stripped.

    "080" -> "80", "080/165" -> "80", " 080 " -> "80", "000" -> "0", "No.080" ->
    "80". Empty, whitespace, or non-digit input yields None — an honest absence
    rather than a fabricated "0".
    """
    if raw is None:
        return None
    s = _DENOM_RE.sub("", raw).strip()
    s = _NONDIGIT_RE.sub("", s)
    if s == "":
        return None
    return s.lstrip("0") or "0"  # "000" -> "0", not ""


def check_consistency(
    ocr_number: str | None,
    card_number: str | None,
    card_id: str | None = None,
    card_name: str | None = None,
) -> ConsistencyResult:
    """Compare a printed number against a catalog number, honestly.

    Resolution order of cases (most honest-first):
      no_card  — no card was recognized; there is nothing to compare against.
      unread  — a card was recognized but OCR read no number; nothing to compare.
      match   — the printed number equals the catalog number (normalized).
      mismatch — they differ; wrong recognition OR counterfeit, indistinguishable.
    """
    printed = _normalize(ocr_number)
    catalog = _normalize(card_number)

    if card_id is None or catalog is None:
        return ConsistencyResult(
            printed_number=printed,
            catalog_number=None,
            card_id=None,
            card_name=None,
            match="no_card",
            note="No card was recognized, so there is no catalog number to check against.",
        )

    if printed is None:
        return ConsistencyResult(
            printed_number=None,
            catalog_number=catalog,
            card_id=card_id,
            card_name=card_name,
            match="unread",
            note="Could not read the printed number from this scan — nothing to compare.",
        )

    if printed == catalog:
        return ConsistencyResult(
            printed_number=printed,
            catalog_number=catalog,
            card_id=card_id,
            card_name=card_name,
            match="match",
            note=f"The printed number ({printed}) matches the catalog for {card_name}.",
        )

    return ConsistencyResult(
        printed_number=printed,
        catalog_number=catalog,
        card_id=card_id,
        card_name=card_name,
        match="mismatch",
        note=(
            f"The printed number ({printed}) does not match the catalog number ({catalog}) "
            f"for {card_name}. This can mean the recognition was wrong, OR the card is a "
            "counterfeit — the app cannot tell which."
        ),
    )