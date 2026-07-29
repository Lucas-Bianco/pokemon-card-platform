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

# A card must occupy at least this fraction of the frame to be considered. Filters out
# specular highlights, logos, and background clutter.
_MIN_AREA_FRACTION = 0.05


def order_corners(points: np.ndarray) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left.

    Uses coordinate sums and differences: the top-left has the smallest x+y, the
    bottom-right the largest; the top-right has the smallest y-x.
    """
    points = np.asarray(points, dtype="float32").reshape(4, 2)
    ordered = np.zeros((4, 2), dtype="float32")

    total = points.sum(axis=1)
    ordered[0] = points[np.argmin(total)]
    ordered[2] = points[np.argmax(total)]

    diff = np.diff(points, axis=1).ravel()
    ordered[1] = points[np.argmin(diff)]
    ordered[3] = points[np.argmax(diff)]
    return ordered


def find_card_corners(image: Image.Image) -> np.ndarray | None:
    """Locate the card's four corners, or None if no plausible quadrilateral is found."""
    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    # Close small gaps so a card edge broken by glare still forms a closed contour.
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    min_area = frame.shape[0] * frame.shape[1] * _MIN_AREA_FRACTION
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < min_area:
            break  # sorted descending, so everything after is smaller too
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            return order_corners(approx.reshape(4, 2).astype("float32"))
    return None


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

    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    matrix = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(frame, matrix, (width, height))
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


def rectify_card(image: Image.Image, size: tuple[int, int]) -> Image.Image | None:
    """Detect and flatten a card. Returns None when no card is found."""
    corners = find_card_corners(image)
    if corners is None:
        return None
    return rectify_from_corners(image, corners, size)
