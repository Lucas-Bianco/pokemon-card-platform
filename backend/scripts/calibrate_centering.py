"""Calibration harness for the card-centering measurement.

Phase 3a, Task 1: settle whether the ~52.6% median worst-axis centering measured
on 12 catalog reference renders is a real property of the images or a bug in the
measurement.

Answer: neither explanation as originally framed. The measurement has no bug --
it is exact on synthetics and provably mirror-equivariant -- but the 52.6% is
also not evidence of off-centre renders. "Worst axis" is max() over four shares,
a statistic that is >= 50% by construction, and the borders are only ~13-30 px
wide, so the unavoidable +-1 px integer quantisation of an edge that does not
land on a pixel boundary already produces a null median of ~51.3%. Run this file
to see all four measurements.

PSA FRONT centering tolerances, verified 2026-07-30 against the publisher:
    https://www.psacard.com/gradingstandards  (the "Grade Definitions" carousel)

    Grade          Front centering       Reverse centering
    10  GEM-MT     55/45                 75/25
     9  MINT       60/40                 90/10
     8  NM-MT      65/35                 90/10
     7  NM         70/30                 90/10
     6  EX-MT      80/20                 90/10
     5  EX         85/15                 90/10
     4  VG-EX      85/15                 90/10
     3  VG         90/10                 90/10
     2  GOOD       90/10                 90/10
     1.5 FR        90/10                 90/10
     1  PR         (no centering figure published)

The five-row table this task was specified with (10=55/45, 9=60/40, 8=65/35,
7=70/30, 6=80/20) matches the published front values exactly -- no correction
needed. Two things the short table omits, both load-bearing here:
  * PSA words grade 10 as centering "within a tolerance not to exceed
    approximately 55/45 percent on the front", and publishes a *Centering Note*
    that "at the grader's sole discretion, a small variance may be permitted on
    occasion based on the card's overall eye appeal". These are not hard cutoffs,
    so a measurement that lands inside its own error bar of a boundary should be
    reported as ambiguous rather than resolved to a grade.
  * Grades 5 and 4 share 85/15, so front centering alone cannot separate them.

Usage:
    python backend/scripts/calibrate_centering.py                # synthetics + null model
    python backend/scripts/calibrate_centering.py --real         # + the 6 reference renders
    python backend/scripts/calibrate_centering.py --real --sample 90
"""

from __future__ import annotations

import argparse
import io
import itertools
import random
import statistics
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from cardplatform.config import settings

# PSA front-centering tolerance per grade, as the worst-side share in percent.
# Verified against psacard.com/gradingstandards (see module docstring).
PSA_FRONT_TOLERANCE = {
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

# The reference renders the Phase 3a prototype reported on.
REFERENCE_CARD_IDS = [
    "base4-44",
    "base5-14",
    "base1-1",
    "base1-37",
    "base3-39",
    "base4-101",
]

# Hi-res renders are cached under data/, alongside the other image caches and
# already gitignored. Nothing here is irreplaceable -- it re-downloads on demand.
CACHE_DIR = settings.data_dir / "centering_cache"
TOLERANCE_PCT = 0.5  # a synthetic case fails above this


# --------------------------------------------------------------------------
# The prototype algorithm, reproduced verbatim. Do not "improve" it here --
# the point of the harness is to score this exact code.
# --------------------------------------------------------------------------
def find_border_widths(pil: Image.Image) -> dict[str, int]:
    bgr = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
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

    hue_diff = np.minimum(
        np.abs(hsv[:, :, 0].astype(np.int16) - border_hue),
        180 - np.abs(hsv[:, :, 0].astype(np.int16) - border_hue),
    )
    is_border = (
        (hue_diff < 12)
        & (np.abs(hsv[:, :, 1].astype(np.int16) - border_sat) < 70)
        & (np.abs(hsv[:, :, 2].astype(np.int16) - border_val) < 70)
    )

    def run_from(profile):
        count = 0
        for value in profile:
            if value < 0.6:
                break
            count += 1
        return count

    rows_border = is_border.mean(axis=1)
    cols_border = is_border.mean(axis=0)
    return {
        "top": run_from(rows_border),
        "bottom": run_from(rows_border[::-1]),
        "left": run_from(cols_border),
        "right": run_from(cols_border[::-1]),
    }


def synthetic_card(
    border_l: int,
    border_r: int,
    border_t: int,
    border_b: int,
    size: tuple[int, int] = (600, 825),
) -> Image.Image:
    """A yellow-bordered card with an exact interior offset, in pixels."""
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


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------
def centering(borders: dict[str, int]) -> tuple[float, float]:
    """(horizontal, vertical) left/top share as a percentage."""
    lr = borders["left"] + borders["right"]
    tb = borders["top"] + borders["bottom"]
    horizontal = borders["left"] / lr * 100 if lr else 50.0
    vertical = borders["top"] / tb * 100 if tb else 50.0
    return horizontal, vertical


def worst_axis(horizontal: float, vertical: float) -> float:
    """Largest of the four shares, e.g. 60/40 -> 60. Always >= 50 by construction."""
    return max(horizontal, 100 - horizontal, vertical, 100 - vertical)


def psa_grade_ceiling(worst: float) -> str:
    for grade in sorted(PSA_FRONT_TOLERANCE, reverse=True):
        if worst <= PSA_FRONT_TOLERANCE[grade]:
            return f"<= {grade}"
    return "< 2"


def fmt_share(value: float) -> str:
    return f"{value:.1f}/{100 - value:.1f}"


def rule(title: str) -> None:
    print()
    print("=" * 104)
    print(title)
    print("=" * 104)


# --------------------------------------------------------------------------
# TEST 1 -- synthetics: centering is exact by construction, so any delta is
# measurement error and nothing else. This is the decisive test.
# --------------------------------------------------------------------------
SYNTHETIC_CASES = [
    # (label, l, r, t, b)
    ("perfect", 20, 20, 20, 20),
    ("slight horizontal", 22, 18, 20, 20),
    ("PSA-9 edge", 24, 16, 20, 20),
    ("vertical", 20, 20, 24, 16),
    ("both axes", 24, 16, 23, 17),
    # thickness sweep at perfect centering -- is any error thickness-dependent?
    ("perfect 6px", 6, 6, 6, 6),
    ("perfect 12px", 12, 12, 12, 12),
    ("perfect 30px", 30, 30, 30, 30),
    ("perfect 60px", 60, 60, 60, 60),
]


def run_synthetics() -> int:
    rule("TEST 1 -- SYNTHETIC CARDS (centering exact by construction; any delta is measurement error)")
    header = (
        f"{'case':<20} {'true l,r,t,b':<16} {'measured l,r,t,b':<18} "
        f"{'exp L/R':<12} {'got L/R':<12} {'exp T/B':<12} {'got T/B':<12} {'err':>7}"
    )
    print(header)
    print("-" * len(header))

    failures = 0
    for label, bl, br, bt, bb in SYNTHETIC_CASES:
        measured = find_border_widths(synthetic_card(bl, br, bt, bb))
        exp_h, exp_v = centering({"left": bl, "right": br, "top": bt, "bottom": bb})
        got_h, got_v = centering(measured)
        error = max(abs(exp_h - got_h), abs(exp_v - got_v))
        failures += error > TOLERANCE_PCT

        truth_s = f"{bl},{br},{bt},{bb}"
        got_s = f"{measured['left']},{measured['right']},{measured['top']},{measured['bottom']}"
        print(
            f"{label:<20} {truth_s:<16} {got_s:<18} "
            f"{fmt_share(exp_h):<12} {fmt_share(got_h):<12} "
            f"{fmt_share(exp_v):<12} {fmt_share(got_v):<12} "
            f"{error:>6.2f}%{'  <-- OFF' if error > TOLERANCE_PCT else ''}"
        )

    print("-" * len(header))
    if failures:
        print(f"  {failures}/{len(SYNTHETIC_CASES)} cases exceed {TOLERANCE_PCT}%. The measurement has a bug.")
        print("  Diagnose the cause -- do NOT paper over it with a constant calibration offset.")
    else:
        print(f"  All {len(SYNTHETIC_CASES)} cases exact (error 0.00%), at every border thickness tested.")
        print("  The run-detection carries no directional bias on clean geometry.")
    return failures


# --------------------------------------------------------------------------
# TEST 2 -- mirror equivariance on the real renders. Synthetics only prove the
# operator is unbiased on ideal input; this proves it on the actual pixels.
# Every stage is either per-pixel or an order-independent aggregation, so
# find_border_widths(mirror(I)) must equal mirror(find_border_widths(I)). If it
# does, a left-wider-than-right reading cannot originate in the code.
# --------------------------------------------------------------------------
def run_symmetry(images: list[tuple[str, Image.Image]]) -> int:
    rule("TEST 2 -- MIRROR EQUIVARIANCE ON REAL RENDERS (flipping must swap the two sides exactly)")
    header = f"{'card':<12} {'original l,r,t,b':<20} {'flip-LR l,r,t,b':<20} {'flip-TB l,r,t,b':<20} {'result':<10}"
    print(header)
    print("-" * len(header))

    failures = 0
    for card_id, image in images:
        original = find_border_widths(image)
        flip_lr = find_border_widths(image.transpose(Image.FLIP_LEFT_RIGHT))
        flip_tb = find_border_widths(image.transpose(Image.FLIP_TOP_BOTTOM))
        ok = (
            flip_lr["left"] == original["right"]
            and flip_lr["right"] == original["left"]
            and flip_tb["top"] == original["bottom"]
            and flip_tb["bottom"] == original["top"]
        )
        failures += not ok

        def s(b: dict[str, int]) -> str:
            return f"{b['left']},{b['right']},{b['top']},{b['bottom']}"

        print(f"{card_id:<12} {s(original):<20} {s(flip_lr):<20} {s(flip_tb):<20} {'ok' if ok else 'ASYMMETRIC':<10}")

    print("-" * len(header))
    if failures:
        print(f"  {failures} card(s) measured asymmetrically under reflection -- the code has a directional bug.")
    else:
        print("  Equivariant on every card. Any left/right or top/bottom difference is in the pixels, not the code.")
    return failures


# --------------------------------------------------------------------------
# TEST 3 -- the quantisation null model. This is what actually explains 52.6%.
# "Worst axis" is max() over four shares, so it is >= 50 by construction and
# can never average to 50 under any noise at all. Borders here are ~13-30 px,
# and a real edge does not land on a pixel boundary, so each side carries +-1 px
# of quantisation. That alone reproduces most of the reported anomaly.
# --------------------------------------------------------------------------
def run_null_model() -> None:
    rule("TEST 3 -- QUANTISATION NULL MODEL (what a PERFECTLY centred card measures at, given +-1 px)")
    header = f"{'true border':<14} {'null median worst-axis':<24} {'null mean':<12} {'P(reads > 50/50)':<18} {'1 px in share pts':<18}"
    print(header)
    print("-" * len(header))

    for base in (13, 20, 26, 30):
        values = [
            worst_axis(*centering({"left": l, "right": r, "top": t, "bottom": b}))
            for l, r, t, b in itertools.product(*[[base - 1, base, base + 1]] * 4)
        ]
        above = 100 * sum(v > 50.001 for v in values) / len(values)
        one_px = (base + 1) / (2 * base) * 100 - 50
        print(
            f"{f'{base} px':<14} {f'{statistics.median(values):.2f}%':<24} "
            f"{f'{statistics.mean(values):.2f}%':<12} {f'{above:.0f}%':<18} {f'+-{one_px:.2f} pts':<18}"
        )

    print("-" * len(header))
    print("  A perfectly centred card does NOT measure 50.0% -- it measures ~51-52% worst-axis.")
    print("  So '52.6% median on renders that should be 50/50' is close to the null, not evidence against it.")
    print("  Consequence for grading: at a 20 px border, one pixel is +-2.4 share points, while the whole")
    print("  PSA 10-to-9 band (55 -> 60) is 5 points wide. This is a RESOLUTION limit, not a bias.")


# --------------------------------------------------------------------------
# TEST 4 -- real catalog renders. Their true centering is unknown, so these
# cannot adjudicate anything; they are here to reproduce the prototype's numbers
# and to check the claimed left/top-wide bias against a larger sample.
# --------------------------------------------------------------------------
def _cache_path(card_id: str) -> Path:
    # Never derive a cache filename from the image URL: 661 catalog images have
    # no extension and two real ids (ex10-!, ex10-?) contain NTFS-illegal
    # characters. Key on card_id and percent-encode it.
    return CACHE_DIR / f"{urllib.parse.quote(card_id, safe='')}.png"


def fetch_image(card_id: str, url: str) -> Image.Image:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(card_id)
    if path.exists():
        return Image.open(path).convert("RGB")
    # images.pokemontcg.io 403s urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cardplatform calibrate)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    image.save(path)
    return image


def load_reference_images(card_ids: list[str]) -> list[tuple[str, Image.Image]]:
    from cardplatform.db.models import Card
    from cardplatform.db.session import Database

    loaded: list[tuple[str, Image.Image]] = []
    with Database().session() as session:
        for card_id in card_ids:
            card = session.get(Card, card_id)
            if card is None or not card.image_large:
                print(f"  skip {card_id}: no image_large in catalog")
                continue
            try:
                loaded.append((card_id, fetch_image(card_id, card.image_large)))
            except Exception as exc:  # noqa: BLE001 - a failed download is not fatal here
                print(f"  skip {card_id}: {exc}")
    return loaded


def detection_looks_sane(borders: dict[str, int], size: tuple[int, int]) -> bool:
    """Reject frames where the colour run clearly latched onto something else.

    Some layouts (full-art, e-card holos) have no uniform outer border, and the
    run then swallows an interior region -- e.g. ecard2-H8 reads left=67 against
    right=21. Those are detector failures, not centering measurements, and
    averaging them in would manufacture an off-centre signal that isn't there.
    """
    width, height = size
    return (
        max(borders["left"], borders["right"]) <= 0.15 * width
        and max(borders["top"], borders["bottom"]) <= 0.15 * height
        and min(borders.values()) >= 3
    )


def run_real(images: list[tuple[str, Image.Image]], title: str, per_card: bool = True) -> None:
    rule(title)
    header = (
        f"{'card':<14} {'size':<12} {'borders l,r,t,b':<20} "
        f"{'L/R':<12} {'T/B':<12} {'worst':>7}  {'PSA ceiling':<12}"
    )
    if per_card:
        print(header)
        print("-" * len(header))

    horizontals: list[float] = []
    verticals: list[float] = []
    worsts: list[float] = []
    rejected = 0

    for card_id, image in images:
        borders = find_border_widths(image)
        if not detection_looks_sane(borders, image.size):
            rejected += 1
            continue
        got_h, got_v = centering(borders)
        worst = worst_axis(got_h, got_v)
        horizontals.append(got_h)
        verticals.append(got_v)
        worsts.append(worst)
        if per_card:
            border_s = f"{borders['left']},{borders['right']},{borders['top']},{borders['bottom']}"
            print(
                f"{card_id:<14} {f'{image.width}x{image.height}':<12} {border_s:<20} "
                f"{fmt_share(got_h):<12} {fmt_share(got_v):<12} "
                f"{worst:>6.1f}%  {psa_grade_ceiling(worst):<12}"
            )

    print("-" * len(header))
    if not worsts:
        print("  no usable measurements")
        return

    def sided(values: list[float], wide: str, narrow: str) -> str:
        high = sum(v > 50.001 for v in values)
        low = sum(v < 49.999 for v in values)
        return f"{wide}-wider {high}, {narrow}-wider {low}, tied {len(values) - high - low}"

    print(f"  n = {len(worsts)} usable, {rejected} rejected as detector failures")
    print(f"  median worst-axis : {statistics.median(worsts):.2f}%")
    print(f"  left  share       : median {statistics.median(horizontals):.2f}%   ({sided(horizontals, 'left', 'right')})")
    print(f"  top   share       : median {statistics.median(verticals):.2f}%   ({sided(verticals, 'top', 'bottom')})")


def load_random_sample(count: int, seed: int) -> list[tuple[str, Image.Image]]:
    from sqlalchemy import select

    from cardplatform.db.models import Card
    from cardplatform.db.session import Database

    with Database().session() as session:
        rows = session.execute(select(Card.id, Card.image_large).where(Card.image_large.isnot(None))).all()
    chosen = random.Random(seed).sample(rows, min(count, len(rows)))

    loaded: list[tuple[str, Image.Image]] = []
    for card_id, url in chosen:
        try:
            loaded.append((card_id, fetch_image(card_id, url)))
        except Exception:  # noqa: BLE001 - skip anything that won't download or decode
            continue
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Centering measurement calibration harness.")
    parser.add_argument("--real", action="store_true", help="also measure catalog renders (downloads, cached)")
    parser.add_argument("--sample", type=int, default=0, help="additionally measure N random catalog renders")
    parser.add_argument("--seed", type=int, default=11, help="random seed for --sample")
    args = parser.parse_args()

    failures = run_synthetics()

    if args.real or args.sample:
        references = load_reference_images(REFERENCE_CARD_IDS)
        if references:
            failures += run_symmetry(references)
            run_real(references, "TEST 4a -- THE PROTOTYPE'S REFERENCE RENDERS (true centering unknown)")

    run_null_model()

    if args.sample:
        sample = load_random_sample(args.sample, args.seed)
        run_real(
            sample,
            f"TEST 4b -- {len(sample)} RANDOM CATALOG RENDERS (does the left/top-wide bias survive a larger n?)",
            per_card=False,
        )

    print()
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
