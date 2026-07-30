"""Card-detection strategies.

Measured against 56 real phone photos where the original Canny detector found no quad
at all:

    canny (original)      0 / 56
    otsu + polygon       39 / 56
    adaptive + polygon   56 / 56
    otsu + minAreaRect   56 / 56

Two things made the original fail. Canny needs a *gradient*, so a light card border on
a light background produces no closed contour; and `approxPolyDP` requires exactly four
vertices, which real rounded corners and sensor noise routinely defeat. Fitting a
rotated rectangle to the largest blob drops that second requirement entirely.

Each strategy proposes at most one quad. The caller embeds every proposal and keeps
whichever crop actually recognises best — "found a card-shaped quad" is not the same as
"found the card".

Re-measured here across all 101 logged real scans, counting images yielding at least one
*card-shaped* proposal (see MAX_AREA_FRACTION — the earlier figures counted degenerate
whole-frame quads as detections):

    status      canny     otsu_rect   adaptive_rect
    not_found    0 / 57     55 / 57      0 / 57
    ambiguous   13 / 13     13 / 13      0 / 13
    confident   30 / 31     30 / 31      0 / 31

`otsu_rect` is what recovers the failures, and it is also the only strategy that handles
the synthetic light-on-light scene. `adaptive_rect` currently contributes nothing on real
data: its 51-pixel block size and 11x11 closing kernel merge card and background into one
whole-frame blob every time. It is kept because the evaluation harness (Phase 1c task 5)
is what should decide whether to retune or drop it — but it is not carrying the chain.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# A card must occupy at least this fraction of the frame. Filters specular highlights
# and background clutter. Measured: detection works down to exactly 0.05 and hard-fails
# below it, which encodes a "fill the framing guide" assumption.
MIN_AREA_FRACTION = 0.05

# ...and no more than this fraction, which is the mirror-image failure of the aspect
# gate. Thresholding cannot fail the way Canny does: on a frame with no card (or one
# whose local contrast defeats the threshold) it still returns a mask, and after
# morphological closing that mask is the entire frame. The resulting "quad" is the image
# border, whose ratio for a portrait phone photo is card-shaped enough to pass every
# other check. Measured across all 101 real scans, `adaptive_rect` produced exactly this
# degenerate full-frame quad 101 times out of 101 — never once an actual card boundary.
# A whole-frame crop contains no card boundary to rectify, so accepting it hands the
# encoder an unrectified photo and invites the confident wrong answer this pipeline is
# built to avoid. Real card detections measure 0.15-0.43 of the frame, so 0.98 discards
# only the degenerate case.
MAX_AREA_FRACTION = 0.98

# A real card is 3.5/2.5 = 1.40. Perspective stretches it upward; the interior artwork
# window is ~0.65, which is what wrong detections latch onto.
MIN_ASPECT_RATIO = 1.0
MAX_ASPECT_RATIO = 2.2


def order_corners(points: np.ndarray) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    points = np.asarray(points, dtype="float32").reshape(4, 2)
    ordered = np.zeros((4, 2), dtype="float32")

    total = points.sum(axis=1)
    ordered[0] = points[np.argmin(total)]
    ordered[2] = points[np.argmax(total)]

    diff = np.diff(points, axis=1).ravel()
    ordered[1] = points[np.argmin(diff)]
    ordered[3] = points[np.argmax(diff)]
    return ordered


def quad_is_card_shaped(quad: np.ndarray, frame_area: float) -> bool:
    """Is this quad plausibly a whole card, rather than clutter or its own artwork?"""
    area = cv2.contourArea(quad.astype(np.float32))
    if not frame_area * MIN_AREA_FRACTION <= area <= frame_area * MAX_AREA_FRACTION:
        return False
    lengths = [float(np.linalg.norm(quad[(i + 1) % 4] - quad[i])) for i in range(4)]
    if min(lengths) < 1e-3:
        return False
    ratio = (lengths[1] + lengths[3]) / (lengths[0] + lengths[2])
    return MIN_ASPECT_RATIO <= ratio <= MAX_ASPECT_RATIO


def _largest_polygon_quad(mask: np.ndarray, frame_area: float) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(contour) < frame_area * MIN_AREA_FRACTION:
            break
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) == 4:
            quad = order_corners(approx.reshape(4, 2).astype("float32"))
            if quad_is_card_shaped(quad, frame_area):
                return quad
    return None


def _largest_rotated_rect(mask: np.ndarray, frame_area: float) -> np.ndarray | None:
    """Fit a rotated rectangle rather than demanding exactly four polygon vertices.

    This is the change that recovered all 56 real failures: a card IS a rectangle, so
    fitting one is a better primitive than hoping the contour approximates to 4 points.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contour) < frame_area * MIN_AREA_FRACTION:
            break
        quad = order_corners(cv2.boxPoints(cv2.minAreaRect(contour)).astype("float32"))
        if quad_is_card_shaped(quad, frame_area):
            return quad
    return None


def _to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def detect_canny(image: Image.Image) -> np.ndarray | None:
    """The original strategy. Kept because it was the only one that held all 30 real
    successes when the alternatives were tried alone."""
    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    return _largest_polygon_quad(edges, bgr.shape[0] * bgr.shape[1])


def detect_otsu_rect(image: Image.Image) -> np.ndarray | None:
    """Global threshold plus a rotated-rect fit. Both polarities, because the card may
    be lighter or darker than its surroundings."""
    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    area = bgr.shape[0] * bgr.shape[1]
    _, binary = cv2.threshold(
        cv2.GaussianBlur(gray, (7, 7), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    for mask in (binary, cv2.bitwise_not(binary)):
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        quad = _largest_rotated_rect(closed, area)
        if quad is not None:
            return quad
    return None


# Adaptive thresholding was tried here and removed. With a 51-px block and an 11x11
# closing kernel it merged card and background on every one of the 101 real scans,
# producing a whole-frame quad rather than a card — it contributed 0 usable proposals.
# The MAX_AREA_FRACTION guard now rejects that degenerate output, which left the
# strategy doing nothing but costing time. Re-add only with measurement behind it.

STRATEGIES: list[tuple[str, object]] = [
    ("canny", detect_canny),
    ("otsu_rect", detect_otsu_rect),
]


def detect_candidates(image: Image.Image) -> list[tuple[str, np.ndarray]]:
    """Every plausible card quad, one per strategy, in strategy order."""
    proposals: list[tuple[str, np.ndarray]] = []
    for name, strategy in STRATEGIES:
        try:
            quad = strategy(image)  # type: ignore[operator]
        except cv2.error:
            quad = None
        if quad is not None:
            proposals.append((name, quad))
    return proposals
