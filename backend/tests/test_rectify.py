import numpy as np
from PIL import Image

from cardplatform.recognition.rectify import order_corners, rectify_card


def _card_on_background(angle_offset=0) -> Image.Image:
    """A bright card-shaped rectangle on a dark background, optionally skewed."""
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
    cv2.rectangle(canvas, (220, 220), (480, 430), (60, 90, 200), -1)
    return Image.fromarray(canvas)


def test_order_corners_returns_tl_tr_br_bl():
    scrambled = np.array([[10, 100], [100, 10], [100, 100], [10, 10]], dtype="float32")

    ordered = order_corners(scrambled)

    assert ordered.tolist() == [[10, 10], [100, 10], [100, 100], [10, 100]]


def test_rectify_returns_canonical_size():
    result = rectify_card(_card_on_background(), size=(600, 825))

    assert result is not None
    assert result.size == (600, 825)


def test_rectify_handles_a_skewed_card():
    result = rectify_card(_card_on_background(angle_offset=45), size=(600, 825))

    assert result is not None
    assert result.size == (600, 825)


def test_rectify_returns_none_when_no_card_present():
    blank = Image.fromarray(np.full((900, 700, 3), 18, dtype=np.uint8))

    assert rectify_card(blank, size=(600, 825)) is None


def test_rectify_ignores_tiny_contours():
    """A speck of light must not be mistaken for a card."""
    import cv2

    canvas = np.full((900, 700, 3), 18, dtype=np.uint8)
    cv2.rectangle(canvas, (10, 10), (40, 50), (240, 240, 240), -1)

    assert rectify_card(Image.fromarray(canvas), size=(600, 825)) is None


def test_rectify_from_corners_uses_supplied_quad():
    """The manual-corner fallback path used when auto-detection fails."""
    image = _card_on_background()
    corners = np.array([[150, 120], [560, 100], [575, 780], [130, 800]], dtype="float32")

    from cardplatform.recognition.rectify import rectify_from_corners

    result = rectify_from_corners(image, corners, size=(600, 825))

    assert result.size == (600, 825)
