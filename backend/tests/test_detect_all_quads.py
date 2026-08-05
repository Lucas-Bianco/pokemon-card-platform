"""Tests for multi-quad detection (Phase 4 bulk cataloger).

detect_all_quads returns every card-shaped quad across strategies + Otsu polarities,
IoU-NMS-deduped. Detection is pure geometry here — no catalog/encoder needed. The
synthetic page is N white rounded-rect "cards" on a dark background, arranged in a grid.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from cardplatform.recognition.detectors import (
    detect_all_quads,
    detect_candidates,
    _iou,
    _nms,
)


def _card(x: int, y: int, w: int = 320, h: int = 448) -> list[tuple[int, int]]:
    """A card-shaped rectangle (1.4 aspect), as 4 corners.

    320x448 = 143360 px²; on the default 1200x1500 page (1800000 px²) that is ~0.080
    of the frame, comfortably above MIN_AREA_FRACTION=0.05 and below MAX_AREA_FRACTION.
    """
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _page(cards: list[list[tuple[int, int]]], size: tuple[int, int] = (1200, 1500)) -> Image.Image:
    """A dark page with N white card rectangles drawn on it."""
    canvas = np.full((size[1], size[0]), 40, dtype=np.uint8)  # dark gray background
    for corners in cards:
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        canvas[y0:y1, x0:x1] = 230  # near-white card
    return Image.fromarray(canvas, mode="L").convert("RGB")


def test_detect_all_quads_finds_every_card_in_a_grid():
    # 3x3 grid of cards -> 9 quads. 60px margins/gaps keep cards from touching
    # (320 wide + 60 gap = 380 step; 448 tall + 40 gap = 488 step, fits 1200x1500).
    cards = [_card(60 + (i % 3) * 380, 40 + (i // 3) * 488) for i in range(9)]
    page = _page(cards)
    quads = detect_all_quads(page)
    assert len(quads) == 9


def test_detect_all_quads_returns_nms_deduped_quads():
    # Two near-identical overlapping quads -> NMS keeps one.
    a = np.array(_card(100, 100), dtype="float32")
    b = np.array(_card(105, 105), dtype="float32")  # ~99% overlap
    assert _iou(a, b) > 0.3
    kept = _nms([a, b], threshold=0.3)
    assert len(kept) == 1


def test_detect_all_quads_rejects_whole_frame_blob():
    # A single full-frame "card" (the degenerate adaptive case) is rejected by MAX_AREA_FRACTION.
    full = _page([_card(0, 0, 1190, 1490)])  # ~0.99 of frame
    quads = detect_all_quads(full)
    assert quads == []


def test_detect_candidates_unchanged_single_card():
    # The single-card path must be untouched — one card -> at least one proposal.
    page = _page([_card(480, 580)])
    proposals = detect_candidates(page)
    assert len(proposals) >= 1
    # ...and detect_all_quads agrees on count for a single card.
    assert len(detect_all_quads(page)) == 1


def test_detect_all_quads_empty_page_returns_empty():
    blank = Image.fromarray(np.full((1500, 1200), 40, dtype=np.uint8), mode="L").convert("RGB")
    assert detect_all_quads(blank) == []


def test_iou_disjoint_is_zero():
    a = np.array(_card(0, 0), dtype="float32")
    b = np.array(_card(800, 800), dtype="float32")  # no overlap
    assert _iou(a, b) == 0.0