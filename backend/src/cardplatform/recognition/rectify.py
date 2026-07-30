"""Finds a card in a photograph and warps it flat.

This is the highest-leverage stage of the pipeline: both the embedding search and the
targeted OCR assume a canonical, angle-corrected image. It is also exactly the input
Phase 3's grade predictor needs for centering measurement, so getting it right here is
reused later.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from cardplatform.recognition.detectors import (  # noqa: F401  (re-exported)
    detect_canny,
    order_corners,
    quad_is_card_shaped,
)


def find_card_corners(image: Image.Image) -> np.ndarray | None:
    """Single-strategy detection, kept for callers that want the original behaviour."""
    return detect_canny(image)


def rectify_from_corners(
    image: Image.Image, corners: np.ndarray, size: tuple[int, int]
) -> Image.Image:
    """Perspective-warp the quad defined by `corners` into a flat rectangle."""
    width, height = size
    source = order_corners(corners)
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype="float32",
    )

    # warpPerspective is channel-agnostic, so there is no reason to detour through BGR
    # and back -- that was two full-image copies per call for an identical result.
    frame = np.array(image.convert("RGB"))
    matrix = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(frame, matrix, (width, height))
    return Image.fromarray(warped)


def rectify_card(image: Image.Image, size: tuple[int, int]) -> Image.Image | None:
    """Detect and flatten a card. Returns None when no card is found."""
    corners = find_card_corners(image)
    if corners is None:
        return None
    return rectify_from_corners(image, corners, size)
