"""Multi-card detection eval (Phase 4) — per-card scoring, no single-card regression."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from cardplatform.recognition.detectors import detect_all_quads


def _quad_iou(a, b):
    a2 = np.asarray(a, dtype="float32")
    b2 = np.asarray(b, dtype="float32")
    inter, _ = cv2.intersectConvexConvex(a2, b2)
    inter = max(float(inter), 0.0)
    ua = cv2.contourArea(a2) + cv2.contourArea(b2) - inter
    return inter / ua if ua > 0 else 0.0


def _page_with_grid(cols: int, rows: int, card_w=320, card_h=448, gap=60, pad=60) -> tuple[Image.Image, list[list[list[int]]]]:
    page_w = pad * 2 + cols * card_w + (cols - 1) * gap
    page_h = pad * 2 + rows * card_h + (rows - 1) * gap
    canvas = np.full((page_h, page_w, 3), 40, dtype=np.uint8)
    truth: list[list[list[int]]] = []
    for r in range(rows):
        for c in range(cols):
            x = pad + c * (card_w + gap)
            y = pad + r * (card_h + gap)
            canvas[y:y + card_h, x:x + card_w] = (230, 230, 230)
            truth.append([[x, y], [x + card_w, y], [x + card_w, y + card_h], [x, y + card_h]])
    return Image.fromarray(canvas, mode="RGB"), truth


def _recall(image, truth):
    detected = [q for _, q in detect_all_quads(image)]
    matched = sum(1 for gt in truth if any(_quad_iou(gt, dq) > 0.5 for dq in detected))
    return matched / len(truth) if truth else 0.0


def test_detect_all_quads_recall_on_3x3_page():
    img, truth = _page_with_grid(3, 3)
    # Allow one edge miss (recall >= 0.8); detection should find most of 9 cards.
    assert _recall(img, truth) >= 0.8


def test_detect_all_quads_recall_on_2x2_page():
    img, truth = _page_with_grid(2, 2)
    assert _recall(img, truth) >= 0.75  # at least 3 of 4


def test_single_card_baseline_unaffected():
    # The batch fixtures/eval do not touch the single-card path: detect_all_quads on a
    # one-card page returns exactly 1 (the single-card detect_candidates contract holds).
    img, truth = _page_with_grid(1, 1)
    detected = detect_all_quads(img)
    assert len(detected) == 1