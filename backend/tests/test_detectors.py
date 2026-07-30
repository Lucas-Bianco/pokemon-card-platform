import cv2
import numpy as np
from PIL import Image

from cardplatform.recognition.detectors import (
    STRATEGIES,
    detect_candidates,
    quad_is_card_shaped,
)


def _scene(card_colour, background_colour, angle=0):
    """A card-shaped rectangle on a background, optionally rotated."""
    canvas = np.full((900, 700, 3), background_colour, dtype=np.uint8)
    box = cv2.boxPoints(((350, 450), (380, 532), angle))
    cv2.fillPoly(canvas, [box.astype(np.int32)], card_colour)
    return Image.fromarray(canvas)


def test_quad_is_card_shaped_accepts_a_real_ratio():
    quad = np.array([[0, 0], [250, 0], [250, 350], [0, 350]], dtype="float32")

    assert quad_is_card_shaped(quad, frame_area=700 * 900) is True


def test_quad_is_card_shaped_rejects_a_landscape_blob():
    """The artwork window inside a card is ~0.65 — this guard is what stopped
    rectification silently returning a stretched crop of the illustration."""
    quad = np.array([[0, 0], [350, 0], [350, 230], [0, 230]], dtype="float32")

    assert quad_is_card_shaped(quad, frame_area=700 * 900) is False


def test_quad_is_card_shaped_rejects_something_tiny():
    quad = np.array([[0, 0], [20, 0], [20, 28], [0, 28]], dtype="float32")

    assert quad_is_card_shaped(quad, frame_area=700 * 900) is False


def test_every_strategy_has_a_name():
    # Two strategies, deliberately: adaptive thresholding was measured contributing
    # 0 usable proposals across all 101 real scans and removed rather than carried.
    assert len(STRATEGIES) >= 2
    assert all(name and callable(fn) for name, fn in STRATEGIES)


def test_light_card_on_dark_background_is_detected():
    assert len(detect_candidates(_scene((225, 225, 220), 18))) >= 1


def test_light_card_on_LIGHT_background_is_detected():
    """The measured real-world failure: 56 of 56 scans found no quad at all,
    because a light border on a light background forms no closed Canny contour."""
    proposals = detect_candidates(_scene((235, 232, 228), 205))

    assert len(proposals) >= 1, "no strategy handled a light-on-light scene"


def test_rotated_card_is_detected():
    assert len(detect_candidates(_scene((225, 225, 220), 18, angle=12))) >= 1


def test_empty_frame_yields_no_proposals():
    blank = Image.fromarray(np.full((900, 700, 3), 18, dtype=np.uint8))

    assert detect_candidates(blank) == []


def test_proposals_are_named_and_well_formed():
    proposals = detect_candidates(_scene((225, 225, 220), 18))

    names = [name for name, _ in proposals]
    assert len(names) == len(set(names)), "at most one proposal per strategy"
    for _, quad in proposals:
        assert quad.shape == (4, 2)
