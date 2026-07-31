"""Measures how far a card's interior sits off-centre inside its border.

Centering is the one PSA sub-grade that is a distance rather than a judgement, so
it is measurable with zero graded training data -- unlike corners, edges and
surface, which this project cannot attempt until it has labelled cards.

The measurement is exact on clean geometry. The calibration harness
(`backend/scripts/calibrate_centering.py`) scored 0.00% error on synthetic cards at
every border thickness from 6 px to 60 px and proved mirror-equivariance on real
renders: there is no directional bias in the run detection. What limits it is
*resolution*. Each edge is located to the nearest pixel, and on a 20 px border one
pixel is worth +-2.5 share points while the entire PSA 10-to-9 band (55 -> 60) is
only 5 points wide:

    true border    +-1 px in share points
       13 px            +-3.85
       20 px            +-2.50
       30 px            +-1.67

So this module cannot reliably separate a 10 from a 9, and it must not pretend to.
It *can* say a 70/30 card is not a 10. Every result therefore carries the
share-point interval implied by +-1 px, and `psa_cap_certain` goes False whenever
that interval straddles a grade boundary -- the same calibrated-uncertainty rule
the recognition pipeline follows for narrow visual margins. Declining beats a
confidently wrong answer.

Known limitation -- modern textured frames cannot be measured by this method at
all. The approach assumes a flat, uniform outer border, so that unequal side
widths imply a miscut. Classic frames satisfy that exactly: all six clean-bordered
reference renders peak at 1.000 border-fraction on every side. Scarlet & Violet
and Mega Evolution era frames do not -- their outer band is textured, the colour
classifier never captures more than ~0.68-0.77 of any row, and the run detector
then stops wherever noise happens to cross its 0.6 threshold. Eight such cards in
a 90-render sample all read top=24 against bottom=8 and were assigned a PSA cap of
6 off a number that was not centering in any sense. `MIN_BORDER_PURITY` rejects
them. Do not try to recover these by lowering the run threshold; the premise of
the measurement, not its tuning, is what fails on a non-uniform border.

Pure module: an image goes in, numbers come out. No I/O, no database, no models.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

# PSA FRONT centering tolerance per grade, as the worst-side share in percent.
# Verified 2026-07-30 against https://www.psacard.com/gradingstandards; see the
# calibration harness docstring for the full front/reverse table.
#
# Two entries look redundant and are kept deliberately, because they document the
# standard rather than the lookup: grades 5 and 4 share 85/15 and grades 3 and 2
# share 90/10, so front centering alone cannot separate those pairs. `psa_cap_for`
# scans high-to-low and so reports the best grade a share still permits.
#
# These are soft limits. PSA words grade 10 as "not to exceed *approximately*
# 55/45 percent on the front" and publishes a Centering Note allowing grader
# discretion for eye appeal -- which is the second reason a reading that lands
# inside its own error bar of a boundary is reported as unsettled.
PSA_FRONT_TOLERANCE: dict[int, float] = {
    10: 55.0,
    9: 60.0,
    8: 65.0,
    7: 70.0,
    6: 80.0,
    5: 85.0,
    4: 85.0,
    3: 90.0,
    2: 90.0,
}

# A border thinner than this in total carries more than +-25 share points of
# quantisation error, which is wider than every PSA band put together.
MIN_TOTAL_BORDER_PX = 4

# A colour run covering most of the frame is a blank or borderless crop, not a
# border. Adaptive thresholding taught this pipeline once already: "found a
# card-shaped region" is not "found the card".
MAX_TOTAL_BORDER_FRACTION = 0.6

# The full-art guard. `ecard2-H8` measured left=67 against right=21 -- a 3.19x
# ratio -- because full-art and e-card layouts have no uniform outer border and
# the run swallows interior artwork instead. 11 of 90 reference renders failed
# this way, and every one would have manufactured an off-centre signal that was
# never in the card.
#
# 3.0x is 75/25. It is deliberately tighter than the 9x a genuine 90/10 card would
# show, and that costs real coverage: a truly miscut card worse than 75/25 is
# declined rather than measured. That trade is the right way round here. This
# module earns its keep in the 50-70 range, where the 10/9/8/7 boundaries live and
# where the difference is invisible to the eye; a card past 75/25 is obviously
# miscut without any measurement, so refusing it costs nothing anyone needed.
# Meanwhile a detector failure landing in that same range is expensive -- it
# invents a grade cap for a card whose border was never found. There is no ratio
# that both admits genuine 80/20 miscuts and rejects the measured 3.19x failure,
# so the module takes the side that never answers wrongly.
MAX_SIDE_RATIO = 3.0

# The textured-frame guard, and the reason `MAX_SIDE_RATIO` alone was not enough.
# A flat border saturates the classifier: every clean reference render peaks at
# exactly 1.000 border-fraction on all four sides. A textured one never can, so the
# 0.6 run threshold ends up decided by noise rather than by an edge.
#
# The two populations are bimodal with an empty band between them. Peak purity
# along the leading run, measured over 90 catalog renders:
#
#     textured SV / ME frames    0.68 - 0.82
#     (nothing in between)
#     clean flat borders         0.99 - 1.00
#
# 0.90 sits in the middle of that gap. The choice is deliberately insensitive:
# every threshold from 0.85 to 0.98 rejects the same 42-43 of the 90 renders, so
# nothing here is balanced on the constant.
#
# This is orthogonal to the ratio gate, and both are needed. `ecard1-122` (l=68,
# r=22) and `ecard3-108` (l=67, r=19) have perfectly clean 1.000 borders and are
# caught only by the ratio; the SV cluster sits at a legal 3.00 ratio and is caught
# only by the purity.
MIN_BORDER_PURITY = 0.90

# The border-colour classifier, ported verbatim from the calibration harness.
# Do not "improve" these: they are the constants the 0.00%-error result was scored
# against.
_HUE_TOLERANCE = 12
_SAT_TOLERANCE = 70
_VAL_TOLERANCE = 70
_RUN_THRESHOLD = 0.6


@dataclass(frozen=True)
class CenteringResult:
    """A centering measurement with its own error bar attached.

    `worst_axis` is max() over all four shares, so it is >= 50 by construction --
    a perfectly centred card still reads ~51-52% once +-1 px quantisation is
    accounted for. Read it against `uncertainty`, never on its own.
    """

    left_right: tuple[float, float]
    top_bottom: tuple[float, float]
    worst_axis: float
    uncertainty: float
    border_pixels: tuple[int, int, int, int]  # left, right, top, bottom
    psa_cap: int | None
    psa_cap_certain: bool


def psa_cap_for(worst_axis: float) -> int | None:
    """The best PSA grade this centering still permits, or None if it permits none.

    The comparison carries a tiny epsilon because a grade must never turn on one
    unit in the last place: a 22/18 px border is exactly 55.0 in decimal but the
    nearest double to it is 55.00000000000001, which would silently read as a 9.
    The published boundary is "approximately 55/45" anyway -- it is not sharper
    than float noise, and `psa_cap_certain` is what actually carries that caveat.
    """
    for grade in sorted(PSA_FRONT_TOLERANCE, reverse=True):
        if worst_axis <= PSA_FRONT_TOLERANCE[grade] + 1e-9:
            return grade
    return None


def _border_scan(
    rectified: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[float, float, float, float]]:
    """Border thickness in pixels and peak purity, each as (left, right, top, bottom).

    Samples the frame's outermost pixels for the border colour, marks every pixel
    within tolerance of it, then walks inward from each side while the row or
    column is still >=60% border. Ported verbatim from the calibration harness.

    Purity is the highest border-fraction reached anywhere along that run -- the
    cleanest the border ever gets on that side. It falls out of the same profile
    the run walk already consumes, so it costs nothing to collect.
    """
    bgr = cv2.cvtColor(np.array(rectified.convert("RGB")), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    margin = max(2, min(width, height) // 100)
    edge_pixels = np.concatenate(
        [
            hsv[:margin].reshape(-1, 3),
            hsv[-margin:].reshape(-1, 3),
            hsv[:, :margin].reshape(-1, 3),
            hsv[:, -margin:].reshape(-1, 3),
        ]
    )
    border_hue = float(np.median(edge_pixels[:, 0]))
    border_sat = float(np.median(edge_pixels[:, 1]))
    border_val = float(np.median(edge_pixels[:, 2]))

    # Hue is circular over 0-180 in OpenCV, so a red border straddling the wrap
    # point would otherwise read as maximally distant from itself.
    raw_hue_diff = np.abs(hsv[:, :, 0].astype(np.int16) - border_hue)
    hue_diff = np.minimum(raw_hue_diff, 180 - raw_hue_diff)
    is_border = (
        (hue_diff < _HUE_TOLERANCE)
        & (np.abs(hsv[:, :, 1].astype(np.int16) - border_sat) < _SAT_TOLERANCE)
        & (np.abs(hsv[:, :, 2].astype(np.int16) - border_val) < _VAL_TOLERANCE)
    )

    def leading_run(profile: np.ndarray) -> tuple[int, float]:
        count = 0
        peak = 0.0
        for value in profile:
            if value < _RUN_THRESHOLD:
                break
            peak = max(peak, float(value))
            count += 1
        return count, peak

    rows_border = is_border.mean(axis=1)
    cols_border = is_border.mean(axis=0)
    sides = (
        leading_run(cols_border),
        leading_run(cols_border[::-1]),
        leading_run(rows_border),
        leading_run(rows_border[::-1]),
    )
    widths = tuple(width for width, _ in sides)
    purities = tuple(purity for _, purity in sides)
    return widths, purities  # type: ignore[return-value]


def _axis_is_usable(
    near: int, far: int, near_purity: float, far_purity: float, extent: int
) -> bool:
    total = near + far
    if total < MIN_TOTAL_BORDER_PX:
        return False
    if total > extent * MAX_TOTAL_BORDER_FRACTION:
        return False
    smaller, larger = min(near, far), max(near, far)
    if smaller == 0 or larger > smaller * MAX_SIDE_RATIO:
        return False
    # Both sides must be flat enough for the run to have found an edge rather than
    # a noise crossing. One clean side does not rescue a textured opposite side --
    # the share is a ratio, so either endpoint being unlocatable spoils it.
    if min(near_purity, far_purity) < MIN_BORDER_PURITY:
        return False
    return True


def measure_centering(rectified: Image.Image) -> CenteringResult | None:
    """Measure centering on a rectified card, or return None if no border is usable.

    None is the honest answer for a full-art layout, a textured modern frame, a
    borderless crop or a frame the detector never found the card in. Nothing
    downstream should have to guess which of those it got -- it just gets no
    measurement.
    """
    width, height = rectified.size
    (left, right, top, bottom), (pl, pr, pt, pb) = _border_scan(rectified)

    if not _axis_is_usable(left, right, pl, pr, width):
        return None
    if not _axis_is_usable(top, bottom, pt, pb, height):
        return None

    horizontal_total = left + right
    vertical_total = top + bottom
    # Multiply before dividing: both operands stay exact integers, so a ratio that
    # is representable comes out exact. `left / total * 100` rounds twice and puts
    # 22/40 px at 55.00000000000001 instead of 55.0.
    left_share = left * 100 / horizontal_total
    top_share = top * 100 / vertical_total

    horizontal_worst = max(left_share, 100 - left_share)
    vertical_worst = max(top_share, 100 - top_share)
    if horizontal_worst >= vertical_worst:
        worst_axis, worst_total = horizontal_worst, horizontal_total
    else:
        worst_axis, worst_total = vertical_worst, vertical_total

    # A 1 px shift of the interior moves one side's share by 1/total of the whole,
    # i.e. 100/total points -- so a 20 px-a-side border (total 40) is +-2.5 points.
    # Derived from the total, not tuned: it is the entire reason thin borders
    # cannot be graded as finely as thick ones.
    uncertainty = 100.0 / worst_total

    cap = psa_cap_for(worst_axis)
    # Certain only if both ends of the interval land in the same band. Clamping the
    # low end at 50 keeps a near-perfect card from being flagged uncertain by an
    # interval that dips below the floor `worst_axis` can structurally reach.
    low = max(50.0, worst_axis - uncertainty)
    high = worst_axis + uncertainty
    certain = psa_cap_for(low) == psa_cap_for(high)

    return CenteringResult(
        left_right=(left_share, 100 - left_share),
        top_bottom=(top_share, 100 - top_share),
        worst_axis=worst_axis,
        uncertainty=uncertainty,
        border_pixels=(left, right, top, bottom),
        psa_cap=cap,
        psa_cap_certain=certain,
    )
