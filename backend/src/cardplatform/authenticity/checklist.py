"""The user-driven physical authenticity checklist (server-sourced so it is versioned).

Every item is something a collector checks by hand — none of it is computed from
the image, because the 600x825 rectified phone crops are too low-resolution for
print forensics (halftone/holo/sharpness were tested and rejected on this data),
and the project has zero confirmed-counterfeit samples to calibrate any learned
check against. Each item carries an honest ``caveat`` stating its limitation.

``applies`` gates an item to the card type at hand: the holographic light test
only applies to holo cards (gate on rarity, since the baseline scans carry no
``variant``). Non-applicable items are still returned so the UI can show them as
"N/A for this card type" rather than silently omitting a check that exists.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    """One physical check a collector performs themselves.

    ``applies`` is False when the check is irrelevant to the card type (e.g. the
    holo light test for a non-holo card). The UI renders those as N/A, not hidden
    — a check that exists but does not apply is honest information.
    """

    id: str
    title: str
    what_to_check: str
    caveat: str
    applies: bool


_ITEMS: tuple[tuple[str, str, str, str, bool], ...] = (
    (
        "rosette",
        "Rosette / dot pattern",
        "Under a 10× loupe, real offset-printed cards show a CMYK rosette dot screen; many fakes show inkjet diffusion or no dots at all.",
        "Needs a loupe or a very sharp macro photo. This app's scans are too low-resolution to check this for you.",
        True,
    ),
    (
        "holo_light",
        "Light test (holographic)",
        "Tilt the card under direct light; real holo foiling shows a rainbow specular shift; fakes often have a flat or painted-on holo.",
        "Only applies to holo / reverse-holo cards, and is lighting-dependent.",
        False,
    ),
    (
        "edge_layering",
        "Edge layering",
        "Look at the cut edge; real cards have a clean, consistent edge; fakes may show a white core, fraying, or uneven lamination.",
        "Edge wear on a real used card can mimic this; judge against a known-real card.",
        True,
    ),
    (
        "stock_opacity",
        "Card stock / opacity",
        "Hold the card to a bright light; real Pokémon stock has a dark core layer and a specific opacity; fakes may be too translucent or lack the core.",
        "Requires physical access to the card — cannot be judged from a photo.",
        True,
    ),
    (
        "font_printing",
        "Font / printing sharpness",
        "Compare the name and number text to a known-real card; fakes often have slightly soft or wrong fonts.",
        "Phone focus and lighting dominate — judge against a real card, not in isolation.",
        True,
    ),
)


def _is_holo(rarity: str | None, variant: str | None) -> bool:
    """A card is holo if its rarity names a holo rarity, or its variant says so.

    The baseline scans carry no variant (NULL), so rarity is the working signal;
    variant is checked too so future variant-aware scans gate correctly.
    """
    haystack = " ".join(filter(None, [rarity, variant])).lower()
    return "holo" in haystack


def checklist_for(rarity: str | None, variant: str | None) -> list[ChecklistItem]:
    """Build the checklist for a card, gating the holo item on card type."""
    holo = _is_holo(rarity, variant)
    items: list[ChecklistItem] = []
    for item_id, title, what, caveat, always in _ITEMS:
        if always:
            items.append(ChecklistItem(item_id, title, what, caveat, True))
        else:
            # The holo light test is the only gated item today.
            items.append(ChecklistItem(item_id, title, what, caveat, holo))
    return items