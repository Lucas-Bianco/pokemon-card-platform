"""Tests for the centering measurement.

Synthetic cards have their centering exact by construction, so any deviation from
the expected share is measurement error and nothing else. If one of these fails,
the algorithm is wrong -- do not widen the tolerance.
"""

import dataclasses

import cv2
import numpy as np
import pytest
from PIL import Image

from cardplatform.grading.centering import (
    CenteringResult,
    measure_centering,
    psa_cap_for,
)


def synthetic_card(
    border_l: int,
    border_r: int,
    border_t: int,
    border_b: int,
    size: tuple[int, int] = (600, 825),
) -> Image.Image:
    """A yellow-bordered card with an exact interior offset, in pixels.

    Copied from backend/scripts/calibrate_centering.py so the module is tested on
    exactly the fixtures the calibration was scored against.
    """
    width, height = size
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:, :] = (30, 200, 240)  # BGR yellow border
    cv2.rectangle(
        canvas,
        (border_l, border_t),
        (width - border_r - 1, height - border_b - 1),
        (90, 60, 40),  # dark interior
        -1,
    )
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))


def speckled_border_card(
    border: int = 20,
    purity: float = 0.70,
    size: tuple[int, int] = (600, 825),
    seed: int = 7,
) -> Image.Image:
    """A centred card whose border is speckled instead of flat.

    Mimics the modern Scarlet & Violet / Mega Evolution frames: the border is
    still the dominant colour, so the run detector still walks the full 20 px and
    every width/ratio guard passes -- but it never saturates. At purity 0.70 the
    profile sits just above the 0.6 run threshold, which is exactly the regime
    where the measured edge is noise rather than geometry.
    """
    array = np.array(synthetic_card(border, border, border, border, size))
    height, width = array.shape[:2]
    outside_interior = np.ones((height, width), dtype=bool)
    outside_interior[border : height - border, border : width - border] = False
    speckle = outside_interior & (np.random.default_rng(seed).random((height, width)) > purity)
    array[speckle] = (20, 40, 90)  # RGB, far from the yellow border in hue
    return Image.fromarray(array)


# ---------------------------------------------------------------------------
# The measurement itself
# ---------------------------------------------------------------------------
def test_perfectly_centred_card_measures_50_50():
    result = measure_centering(synthetic_card(20, 20, 20, 20))

    assert result is not None
    assert result.left_right == pytest.approx((50.0, 50.0), abs=1.0)
    assert result.top_bottom == pytest.approx((50.0, 50.0), abs=1.0)
    assert result.border_pixels == (20, 20, 20, 20)


def test_horizontal_offset_measures_60_40():
    result = measure_centering(synthetic_card(24, 16, 20, 20))

    assert result is not None
    assert result.left_right == pytest.approx((60.0, 40.0), abs=1.0)
    assert result.top_bottom == pytest.approx((50.0, 50.0), abs=1.0)


def test_vertical_offset_measures_60_40():
    result = measure_centering(synthetic_card(20, 20, 24, 16))

    assert result is not None
    assert result.top_bottom == pytest.approx((60.0, 40.0), abs=1.0)
    assert result.left_right == pytest.approx((50.0, 50.0), abs=1.0)


def test_worst_axis_is_the_largest_share_across_both_axes():
    """Horizontal reads 55/45 and vertical 60/40, so the worst axis is the vertical."""
    result = measure_centering(synthetic_card(22, 18, 24, 16))

    assert result is not None
    assert result.left_right == pytest.approx((55.0, 45.0), abs=1.0)
    assert result.top_bottom == pytest.approx((60.0, 40.0), abs=1.0)
    assert result.worst_axis == pytest.approx(60.0, abs=1.0)


def test_worst_axis_picks_the_minority_side_when_it_is_larger():
    """A card offset the other way reads 40/60, and the worst axis is still 60."""
    result = measure_centering(synthetic_card(16, 24, 20, 20))

    assert result is not None
    assert result.left_right == pytest.approx((40.0, 60.0), abs=1.0)
    assert result.worst_axis == pytest.approx(60.0, abs=1.0)


# ---------------------------------------------------------------------------
# Guards -- each declines rather than inventing a number
# ---------------------------------------------------------------------------
def test_blank_image_returns_none():
    """Uniform grey has no interior, so the colour run swallows the whole frame."""
    blank = Image.fromarray(np.full((825, 600, 3), 128, dtype=np.uint8))

    assert measure_centering(blank) is None


def test_too_little_border_returns_none():
    """A 1 px border cannot be measured to better than +-50 share points."""
    assert measure_centering(synthetic_card(1, 1, 1, 1)) is None


def test_grossly_asymmetric_border_is_rejected():
    """The real ecard2-H8 failure: a full-art layout read left=67 against right=21.

    There is no uniform outer border to measure, so the run latched onto interior
    artwork. Accepting it would manufacture a 76/24 reading -- a confidently wrong
    grade cap on a card whose centering was never measured at all.
    """
    assert measure_centering(synthetic_card(67, 21, 20, 20)) is None


def test_asymmetric_vertical_border_is_rejected_too():
    """The guard is per-axis, not horizontal-only."""
    assert measure_centering(synthetic_card(20, 20, 67, 21)) is None


def test_textured_border_is_rejected():
    """The modern SV/ME frame failure: a border that never reads as a flat colour.

    Eight cards in a 90-render sample shared one signature -- top=24 against
    bottom=8, a legal 3.00 ratio -- and were handed psa_cap=6 off a reading that
    was not centering at all. Their borders peak at 0.68-0.77 purity where a real
    flat border saturates at 1.000.

    Without the purity guard this fixture passes every other gate and returns a
    confident 50/50, because the speckled border still clears the 0.6 run
    threshold on all four sides.
    """
    assert measure_centering(speckled_border_card(purity=0.70)) is None


def test_a_clean_border_from_the_same_fixture_is_accepted():
    """Pairs with the textured test: at purity 1.0 the fixture is an ordinary card.

    Only the speckling differs, so the guard is discriminating on border quality
    and not on some incidental property of how the fixture is built.
    """
    result = measure_centering(speckled_border_card(purity=1.0))

    assert result is not None
    assert result.border_pixels == (20, 20, 20, 20)
    assert result.worst_axis == pytest.approx(50.0, abs=1.0)


def test_a_genuine_miscut_inside_the_ratio_gate_is_still_measured():
    """Pairs with the rejection tests so the gate cannot pass by rejecting everything.

    l=28/r=12 is 70/30 -- a real PSA-7 miscut, a 2.33x ratio, comfortably measurable.
    """
    result = measure_centering(synthetic_card(28, 12, 20, 20))

    assert result is not None
    assert result.worst_axis == pytest.approx(70.0, abs=1.0)
    assert result.psa_cap == 7


# ---------------------------------------------------------------------------
# The PSA cap
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("worst", "expected"),
    [
        (52.0, 10),
        (55.0, 10),
        (57.0, 9),
        (60.0, 9),
        (63.0, 8),
        (68.0, 7),
        (75.0, 6),
        (95.0, None),
    ],
)
def test_psa_cap_for_thresholds(worst, expected):
    assert psa_cap_for(worst) == expected


# ---------------------------------------------------------------------------
# Uncertainty -- the resolution limit, made testable
# ---------------------------------------------------------------------------
def test_thin_border_is_less_certain_than_thick():
    """One pixel is worth more share points the thinner the border is.

    6 px a side is a 12 px total (+-8.33 pts); 60 px a side is 120 px (+-0.83 pts).
    """
    thin = measure_centering(synthetic_card(6, 6, 6, 6))
    thick = measure_centering(synthetic_card(60, 60, 60, 60))

    assert thin is not None and thick is not None
    assert thin.uncertainty > thick.uncertainty
    assert thin.uncertainty == pytest.approx(100 / 12, abs=0.01)
    assert thick.uncertainty == pytest.approx(100 / 120, abs=0.01)


def test_cap_is_uncertain_when_the_interval_straddles_a_boundary():
    """55.0 +- 2.5 spans 52.5-57.5, which crosses the 55/45 line between 10 and 9.

    The cap is still reported as 10 -- but flagged as not settled, because this
    measurement cannot separate a 10 from a 9 at a 20 px border.
    """
    result = measure_centering(synthetic_card(22, 18, 20, 20))

    assert result is not None
    assert result.worst_axis == pytest.approx(55.0, abs=1.0)
    assert result.uncertainty == pytest.approx(2.5, abs=0.01)
    assert result.psa_cap == 10
    assert result.psa_cap_certain is False


def test_cap_is_certain_well_inside_a_band():
    """A thick, evenly centred border reads 50.0 +- 0.83 -- nowhere near 55."""
    result = measure_centering(synthetic_card(60, 60, 60, 60))

    assert result is not None
    assert result.psa_cap == 10
    assert result.psa_cap_certain is True


# ---------------------------------------------------------------------------
# The result type
# ---------------------------------------------------------------------------
def test_centering_result_is_frozen():
    result = measure_centering(synthetic_card(20, 20, 20, 20))

    assert isinstance(result, CenteringResult)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.worst_axis = 99.0  # type: ignore[misc]
