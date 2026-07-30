import numpy as np
from PIL import Image

from cardplatform.recognition.rectify import order_corners, rectify_card

# The marker sits well inside the card's top-left quadrant for both the square-on and
# the skewed fixture, so its position in the rectified output pins corner ordering.
_MARKER = ((215, 200), (330, 340))


def _card_on_background(angle_offset=0) -> Image.Image:
    """A bright card-shaped rectangle on a dark background, optionally skewed.

    The blue marker is deliberately off-centre: a rectification that mirrored or
    rotated the card would still be 600x825, so only the marker's landing quadrant
    can distinguish a correct warp from a confidently wrong one.
    """
    import cv2

    canvas = np.full((900, 700, 3), 18, dtype=np.uint8)
    pts = np.array(
        [
            [150 + angle_offset, 120],
            [560, 100 + angle_offset],
            [575 - angle_offset, 780],
            [130, 800 - angle_offset],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(canvas, [pts], (225, 225, 220))
    cv2.rectangle(canvas, _MARKER[0], _MARKER[1], (60, 90, 200), -1)
    return Image.fromarray(canvas)


def _marker_quadrant_counts(image: Image.Image) -> dict[str, int]:
    """Count marker pixels per quadrant of a rectified image."""
    arr = np.array(image)
    marker = (arr[:, :, 2] > 150) & (arr[:, :, 0] < 120)
    height, width = marker.shape
    top, bottom = slice(0, height // 2), slice(height // 2, height)
    left, right = slice(0, width // 2), slice(width // 2, width)
    return {
        "top_left": int(marker[top, left].sum()),
        "top_right": int(marker[top, right].sum()),
        "bottom_left": int(marker[bottom, left].sum()),
        "bottom_right": int(marker[bottom, right].sum()),
    }


def _solid_quad(height: int, width: int) -> Image.Image:
    """A single bright axis-aligned rectangle of the given shape on a dark background."""
    import cv2

    canvas = np.full((900, 700, 3), 18, dtype=np.uint8)
    x0, y0 = 100, 150
    cv2.rectangle(canvas, (x0, y0), (x0 + width, y0 + height), (225, 225, 220), -1)
    return Image.fromarray(canvas)


def test_order_corners_returns_tl_tr_br_bl():
    scrambled = np.array([[10, 100], [100, 10], [100, 100], [10, 10]], dtype="float32")

    ordered = order_corners(scrambled)

    assert ordered.tolist() == [[10, 10], [100, 10], [100, 100], [10, 100]]


def test_rectify_returns_canonical_size():
    result = rectify_card(_card_on_background(), size=(600, 825))

    assert result is not None
    assert result.size == (600, 825)


def test_rectify_places_the_marker_in_the_expected_quadrant():
    """Guards corner ordering, the warp itself, and non-mirroring in one assertion.
    Size alone is free -- rectify_from_corners always returns exactly `size`."""
    result = rectify_card(_card_on_background(), size=(600, 825))

    counts = _marker_quadrant_counts(result)

    assert counts["top_left"] > 0
    assert counts["top_left"] > 0.9 * sum(counts.values())


def test_rectify_handles_a_skewed_card():
    result = rectify_card(_card_on_background(angle_offset=45), size=(600, 825))

    assert result is not None
    assert result.size == (600, 825)
    counts = _marker_quadrant_counts(result)
    assert counts["top_left"] > 0.9 * sum(counts.values())


def test_rectify_returns_none_when_no_card_present():
    blank = Image.fromarray(np.full((900, 700, 3), 18, dtype=np.uint8))

    assert rectify_card(blank, size=(600, 825)) is None


def test_rectify_ignores_tiny_contours():
    """A speck of light must not be mistaken for a card."""
    import cv2

    canvas = np.full((900, 700, 3), 18, dtype=np.uint8)
    cv2.rectangle(canvas, (10, 10), (40, 50), (240, 240, 240), -1)

    assert rectify_card(Image.fromarray(canvas), size=(600, 825)) is None


def test_rectify_rejects_a_landscape_quad():
    """A large, clean, four-sided region that is not card-shaped must yield None.

    Height/width here is 0.65, matching the interior artwork window that detection
    latches onto on pale backgrounds and when the card is clipped by the frame edge.
    Without the aspect gate that window warps to exactly 600x825 with no border, no
    name bar and no collector number -- the encoder then scores it confidently and
    the pipeline reports a wrong card instead of not_found.
    """
    assert rectify_card(_solid_quad(height=325, width=500), size=(600, 825)) is None


def test_rectify_still_accepts_a_card_shaped_quad():
    """Pairs with the rejection test so the gate cannot pass by rejecting everything."""
    result = rectify_card(_solid_quad(height=560, width=400), size=(600, 825))

    assert result is not None
    assert result.size == (600, 825)


def test_rectify_from_corners_uses_supplied_quad():
    """The manual-corner fallback path used when auto-detection fails."""
    image = _card_on_background()
    corners = np.array([[150, 120], [560, 100], [575, 780], [130, 800]], dtype="float32")

    from cardplatform.recognition.rectify import rectify_from_corners

    result = rectify_from_corners(image, corners, size=(600, 825))

    assert result.size == (600, 825)
    counts = _marker_quadrant_counts(result)
    assert counts["top_left"] > 0.9 * sum(counts.values())
