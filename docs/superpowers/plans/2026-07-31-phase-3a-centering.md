# Phase 3a — Card Centering Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure a card's centering precisely enough to tell the user the best PSA grade their centering allows — and refuse to claim more than that.

**Architecture:** Centering is purely geometric, so it needs no training data. Find the coloured border on each side of the already-rectified crop, compare opposite widths, and map the worse axis onto PSA's published tolerances. Report it as a *cap*, never as a predicted grade.

**Tech Stack:** OpenCV + NumPy on the existing recognition pipeline; a new API field and a small UI panel.

---

## Scope: why this is Phase 3**a**, not Phase 3

The roadmap's Phase 3 is a grade predictor scoring **centering, corners, edges, and surface**, plus the
EV of grading. Three of those four, and the EV, are **blocked**:

- **Corners, edges, surface need labelled training data** — graded cards with known PSA/CGC grades.
  This project has **zero**. No amount of engineering substitutes for that.
- **Grading EV needs graded-card prices** (what a PSA 9 vs PSA 10 of this card sells for). The
  current price source publishes raw prices only.

**Centering is the exception, and that is the whole reason this phase exists.** It is a distance
measurement. A ruler needs no training set. It is also the single most common reason a card misses a
10, so it is the most useful of the four to ship alone.

**Explicitly out of scope:** any overall grade prediction, any corner/edge/surface score, and any
"should I grade this?" EV figure. Shipping those without data would be exactly the confidently-wrong
output this project is built to avoid.

---

## Measured findings this plan is built on

**Verified 2026-07-31.** A prototype measured border widths on 12 catalog reference renders by
sampling the border colour at the extreme edge, classifying pixels by HSV proximity, then taking the
leading run on each side.

It works mechanically — border widths came out consistent at 16–22 px, and two cards measured exactly
50/50:

```
card         L/R      T/B    worst   borders(l,r,t,b)
base4-44   50/50    50/50     50%    20,20,20,20
base5-14   50/50    50/50     50%    18,18,20,20
base1-1    54/46    54/46     54%    19,16,19,16
base4-101  55/45    54/46     55%    21,17,21,18
```

**But the median worst-axis over the 12 was 52.6%, on images that should be 50/50**, with left and
top reading wider than right and bottom in 10 of 12.

**This is the single most important fact in this plan.** PSA 10 requires 55/45 or better on the
front. A systematic 2.6% error is more than half that entire tolerance band — enough to turn a real
10 into a reported 9, or the reverse. **The measurement is not usable until this is resolved**, which
is why Task 1 does nothing but settle it.

Two candidate explanations, both open:
1. The renders genuinely are slightly off-centre — they derive from real print files.
2. The run-detection has a directional bias.

Ruled out already: image resizing. The `_hires` images are already 600×825, and measuring native
versus resized gave identical results to the decimal.

---

## PSA centering tolerances (the thresholds this maps onto)

| Grade | Front centering | Back centering |
|---|---|---|
| **10** Gem Mint | 55/45 or better | 75/25 or better |
| **9** Mint | 60/40 or better | 90/10 or better |
| **8** NM-MT | 65/35 or better | 90/10 or better |
| **7** NM | 70/30 or better | 90/10 or better |
| **6** EX-MT | 80/20 or better | 90/10 or better |

Front only is measured here — the app photographs one face. **That is a limitation to state in the
UI**, because a card with perfect front centering can still be capped by its back.

> **Task 1 must verify these figures against PSA's current published grading standards** rather than
> trusting this table. They are reproduced from general knowledge and are the kind of thing that
> changes. If they differ, use the published values and correct this table.

---

## File structure

```
backend/src/cardplatform/grading/
  __init__.py
  centering.py     # border widths -> centering percentages -> PSA cap
backend/tests/
  test_centering.py
backend/scripts/
  calibrate_centering.py   # Task 1: settle the 2.6% question
backend/src/cardplatform/
  api.py           # + centering on the recognize response
frontend/src/
  components/CenteringPanel.tsx
  api/types.ts, components/ScanResult.tsx
```

`centering.py` is pure — image in, numbers out, no I/O — so the geometry can be tested against
synthetic cards with known, exact centering.

---

## Task 1: Settle the calibration question

**Nothing else in this plan is trustworthy until this is done.** No production code in this task.

**Files:** Create `backend/scripts/calibrate_centering.py`

- [ ] **Step 1: Verify the PSA tolerance table**

Look up PSA's current published centering standards. Confirm or correct the table above, and record
the source URL in the script's docstring. If the figures differ, the corrected values are what Task 3
implements.

- [ ] **Step 2: Build synthetic cards with known-exact centering**

This is the decisive test: a generated card whose centering is *known by construction* separates a
measurement bug from genuine asymmetry in real renders.

```python
"""Settles whether the measured 2.6% centering bias is real or a measurement artefact.

A prototype measured a median worst-axis of 52.6% across 12 catalog renders that should
be 50/50, with left and top consistently wider. Resizing was ruled out. This generates
cards whose centering is exact by construction, so any deviation is measurement error.
"""

import cv2
import numpy as np
from PIL import Image


def synthetic_card(border_l, border_r, border_t, border_b, size=(600, 825)):
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
```

- [ ] **Step 3: Measure the synthetics and report the error**

For each case below, measure with the prototype algorithm and print measured-vs-expected:

| case | l, r, t, b | expected L/R | expected T/B |
|---|---|---|---|
| perfect | 20, 20, 20, 20 | 50/50 | 50/50 |
| slight horizontal | 22, 18, 20, 20 | 55/45 | 50/50 |
| PSA-9 edge | 24, 16, 20, 20 | 60/40 | 50/50 |
| vertical | 20, 20, 24, 16 | 50/50 | 60/40 |
| both axes | 24, 16, 23, 17 | 60/40 | 57.5/42.5 |

**Interpretation, and what each outcome means for the rest of the plan:**
- **Synthetics measure exactly right** → the algorithm is sound and the 2.6% is genuine asymmetry in
  real print renders. Proceed to Task 2 unchanged, and note in the docstring that real cards are not
  perfectly centred.
- **Synthetics are off by a constant** → a measurement bug. Find and fix it in Task 2. Do not paper
  over it with a calibration offset; a constant fudge factor will not hold across border colours and
  widths.

- [ ] **Step 4: Report the finding**

State plainly which outcome occurred and the measured errors. **If the algorithm is wrong, say so and
stop** — Task 2 needs the corrected approach, not the prototype's.

---

## Task 2: The centering module

**Files:**
- Create: `backend/src/cardplatform/grading/__init__.py` (empty)
- Create: `backend/src/cardplatform/grading/centering.py`
- Test: `backend/tests/test_centering.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_centering.py`:

```python
import cv2
import numpy as np
import pytest
from PIL import Image

from cardplatform.grading.centering import CenteringResult, measure_centering, psa_cap_for


def card(border_l=20, border_r=20, border_t=20, border_b=20, size=(600, 825)):
    """A yellow-bordered card with an interior offset that is exact by construction."""
    width, height = size
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:, :] = (30, 200, 240)
    cv2.rectangle(
        canvas, (border_l, border_t), (width - border_r - 1, height - border_b - 1), (90, 60, 40), -1
    )
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))


def test_perfectly_centred_card_measures_fifty_fifty():
    result = measure_centering(card())

    assert result is not None
    assert result.left_right == pytest.approx((50.0, 50.0), abs=1.5)
    assert result.top_bottom == pytest.approx((50.0, 50.0), abs=1.5)


def test_horizontal_offset_is_measured():
    result = measure_centering(card(border_l=24, border_r=16))

    assert result.left_right == pytest.approx((60.0, 40.0), abs=1.5)
    assert result.top_bottom == pytest.approx((50.0, 50.0), abs=1.5)


def test_vertical_offset_is_measured():
    result = measure_centering(card(border_t=24, border_b=16))

    assert result.top_bottom == pytest.approx((60.0, 40.0), abs=1.5)


def test_worst_axis_reports_the_larger_share():
    result = measure_centering(card(border_l=22, border_r=18, border_t=24, border_b=16))

    assert result.worst_axis == pytest.approx(60.0, abs=1.5)


def test_no_border_returns_none():
    """A crop with no detectable border must decline, not invent a number."""
    plain = Image.fromarray(np.full((825, 600, 3), 128, dtype=np.uint8))

    assert measure_centering(plain) is None


def test_psa_cap_thresholds():
    assert psa_cap_for(52.0) == 10
    assert psa_cap_for(55.0) == 10
    assert psa_cap_for(57.0) == 9
    assert psa_cap_for(60.0) == 9
    assert psa_cap_for(63.0) == 8
    assert psa_cap_for(68.0) == 7
    assert psa_cap_for(75.0) == 6
    assert psa_cap_for(95.0) is None


def test_result_is_frozen():
    result = measure_centering(card())

    with pytest.raises(Exception):
        result.worst_axis = 1.0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_centering.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.grading'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/grading/__init__.py`: empty.

`backend/src/cardplatform/grading/centering.py`. Start from the prototype below, **incorporating
whatever Task 1 established**. The docstring must record Task 1's finding.

```python
"""Measures card centering from a rectified crop.

Centering is the one PSA sub-grade that needs no training data: it is a distance
measurement, not a judgement. That matters because this project has zero graded cards
to learn corners, edges, or surface from.

Method: sample the border colour at the extreme edge, classify pixels by HSV proximity
to it, then take the leading run of border-coloured rows/columns on each side. HSV
rather than luminance, because the border is a strong flat colour while the interior
artwork is varied — the saturation/hue step is far cleaner than a brightness step.

Reports a CAP, never a grade. Perfect centering does not make a card a 10; it only
means centering is not what stops it being one.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

# PSA front-centering tolerances, worse axis as the larger share.
# VERIFY against PSA's published standards in Task 1 before trusting these.
_PSA_FRONT_TOLERANCES: list[tuple[float, int]] = [
    (55.0, 10),
    (60.0, 9),
    (65.0, 8),
    (70.0, 7),
    (80.0, 6),
]

_HUE_TOLERANCE = 12
_SAT_TOLERANCE = 70
_VAL_TOLERANCE = 70
_BORDER_ROW_FRACTION = 0.6
_MIN_BORDER_PIXELS = 4


@dataclass(frozen=True)
class CenteringResult:
    left_right: tuple[float, float]
    top_bottom: tuple[float, float]
    worst_axis: float
    border_pixels: tuple[int, int, int, int]  # left, right, top, bottom


def psa_cap_for(worst_axis: float) -> int | None:
    """Best PSA grade this centering allows, or None if it is outside every band."""
    for tolerance, grade in _PSA_FRONT_TOLERANCES:
        if worst_axis <= tolerance:
            return grade
    return None


def measure_centering(rectified: Image.Image) -> CenteringResult | None:
    """Measure border widths and convert them to centering percentages.

    Returns None when no border can be found — declining is correct, because an
    invented centering figure would be acted on.
    """
    bgr = cv2.cvtColor(np.array(rectified.convert("RGB")), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    margin = max(2, min(width, height) // 100)
    edge = np.concatenate(
        [
            hsv[:margin].reshape(-1, 3),
            hsv[-margin:].reshape(-1, 3),
            hsv[:, :margin].reshape(-1, 3),
            hsv[:, -margin:].reshape(-1, 3),
        ]
    )
    hue, sat, val = (float(np.median(edge[:, i])) for i in range(3))

    hue_delta = np.abs(hsv[:, :, 0].astype(np.int16) - hue)
    hue_delta = np.minimum(hue_delta, 180 - hue_delta)
    is_border = (
        (hue_delta < _HUE_TOLERANCE)
        & (np.abs(hsv[:, :, 1].astype(np.int16) - sat) < _SAT_TOLERANCE)
        & (np.abs(hsv[:, :, 2].astype(np.int16) - val) < _VAL_TOLERANCE)
    )

    def leading_run(profile: np.ndarray) -> int:
        count = 0
        for value in profile:
            if value < _BORDER_ROW_FRACTION:
                break
            count += 1
        return count

    rows = is_border.mean(axis=1)
    cols = is_border.mean(axis=0)
    top, bottom = leading_run(rows), leading_run(rows[::-1])
    left, right = leading_run(cols), leading_run(cols[::-1])

    horizontal = left + right
    vertical = top + bottom
    if horizontal < _MIN_BORDER_PIXELS or vertical < _MIN_BORDER_PIXELS:
        return None
    # A run covering most of the image is not a border — it is a blank crop.
    if horizontal > width * 0.6 or vertical > height * 0.6:
        return None

    left_right = (left / horizontal * 100, right / horizontal * 100)
    top_bottom = (top / vertical * 100, bottom / vertical * 100)
    return CenteringResult(
        left_right=left_right,
        top_bottom=top_bottom,
        worst_axis=max(max(left_right), max(top_bottom)),
        border_pixels=(left, right, top, bottom),
    )
```

- [ ] **Step 4: Run the tests**

Expected: 8 passed. **If the synthetic tests fail, the algorithm is wrong** — fix the algorithm, not
the tolerances. A synthetic card's centering is exact by construction.

- [ ] **Step 5: Re-run the reference-render check**

Measure the same 12 catalog renders from the research. Report the median worst-axis and compare it
against the prototype's 52.6%. State whether Task 1's fix moved it.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/grading backend/tests/test_centering.py && git commit -m "feat: measure card centering against PSA tolerances"
```

---

## Task 3: Expose centering on the recognize response

**Files:**
- Modify: `backend/src/cardplatform/recognition/service.py`, `backend/src/cardplatform/api.py`
- Test: `backend/tests/test_recognize_api.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_recognize_api.py`:

```python
def test_recognize_returns_centering_when_measurable(seeded):
    from cardplatform.grading.centering import CenteringResult

    result = RecognitionResult(
        card_id="base1-4",
        confidence=0.97,
        status="confident",
        candidates=(Candidate("base1-4", 0.91),),
        ocr=OcrReading(),
        visual_margin=0.2,
    )
    centering = CenteringResult(
        left_right=(58.0, 42.0), top_bottom=(51.0, 49.0), worst_axis=58.0,
        border_pixels=(23, 17, 20, 19),
    )

    class StubWithCentering:
        def recognize(self, image, rectify=True, corners=None):
            return result, centering

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_recognition_service] = lambda: StubWithCentering()
    client = TestClient(app)

    body = client.post("/recognize", files={"file": ("c.png", _png(), "image/png")}).json()

    assert body["centering"]["worst_axis"] == 58.0
    assert body["centering"]["psa_cap"] == 9
    assert body["centering"]["left_right"] == [58.0, 42.0]


def test_centering_is_null_when_not_measurable(seeded):
    result = RecognitionResult(None, 0.0, "not_found", (), OcrReading(), 0.0)

    class StubNoCentering:
        def recognize(self, image, rectify=True, corners=None):
            return result, None

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_recognition_service] = lambda: StubNoCentering()

    body = TestClient(app).post(
        "/recognize", files={"file": ("c.png", _png(), "image/png")}
    ).json()

    assert body["centering"] is None
```

**Note the signature change:** `recognize()` now returns `(RecognitionResult, CenteringResult | None)`.
Update every existing caller and every existing stub in `test_recognize_api.py` and
`test_recognition_service.py` accordingly. Do not add a second method — one call already produces the
rectified crop centering needs, and rectifying twice would be waste.

- [ ] **Step 2: Run it, confirm it fails**

- [ ] **Step 3: Return centering from the service**

In `recognition/service.py`, add the import and change `_fuse_for` to also measure centering on the
crop it was handed. That crop is already the winner, so centering is measured exactly once — not per
proposal.

```python
from cardplatform.grading.centering import CenteringResult, measure_centering
```

```python
    def _fuse_for(
        self, crop: Image.Image, found: tuple
    ) -> tuple[RecognitionResult, CenteringResult | None]:
        catalog_numbers = self._collector_numbers([c.card_id for c in found])
        candidates = tuple(c for c in found if c.card_id in catalog_numbers)
        reading = self.reader.read(crop)
        result = fuse(candidates, reading, catalog_numbers, config=self.fusion_config)
        # Measured on the winning crop only. Centering is cheap, but so is being tidy:
        # the losing proposals were never the card.
        return result, measure_centering(crop)
```

Every `return` in `recognize()` must now yield a 2-tuple. The early `not_found` path — where no quad
was detected at all — has no crop to measure, so it returns `(result, None)`:

```python
        proposals = detect_candidates(image)
        if not proposals:
            logger.info("no card detected in frame by any strategy")
            return (
                RecognitionResult(
                    card_id=None,
                    confidence=0.0,
                    status="not_found",
                    candidates=(),
                    ocr=OcrReading(),
                    visual_margin=0.0,
                ),
                None,
            )
```

`_recognize_crop` already delegates to `_fuse_for`, so it inherits the new return type unchanged.

- [ ] **Step 4: Add the API model and field**

```python
class CenteringOut(BaseModel):
    left_right: tuple[float, float]
    top_bottom: tuple[float, float]
    worst_axis: float
    psa_cap: int | None
```

Add `centering: CenteringOut | None` to `RecognizeOut` and populate it via `psa_cap_for`.

- [ ] **Step 5: Run the full suite.** All must pass.

- [ ] **Step 6: Commit**

---

## Task 4: Show it, and say what it does not mean

**Files:**
- Create: `frontend/src/components/CenteringPanel.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/components/ScanResult.tsx`, `frontend/src/styles.css`

- [ ] **Step 1: Add the types**

```ts
export interface Centering {
  left_right: [number, number];
  top_bottom: [number, number];
  worst_axis: number;
  psa_cap: number | null;
}
```

Add `centering: Centering | null` to `RecognizeResponse`.

- [ ] **Step 2: Write `CenteringPanel.tsx`**

It must show the two axis ratios, the worse axis, and the cap — **worded as a ceiling, not a
prediction**:

> Centering allows up to **PSA 9**

and never "This card is a PSA 9".

It must also carry two caveats, because omitting them would overstate what was measured:
- **Front only.** The back is not photographed and can cap the grade independently.
- **Centering is one of four criteria.** Corners, edges, and surface are not assessed, and any of
  them can lower the grade further.

When `centering` is null, render nothing rather than an empty panel.

- [ ] **Step 3: Render it in `ScanResult`** beneath the card details, only when present.

- [ ] **Step 4: Build and test**

```bash
npm --prefix C:\ClaudeKnowledge\frontend run build
npm --prefix C:\ClaudeKnowledge\frontend test
```

- [ ] **Step 5: Commit**

---

## Task 5: Measure it on the real scans

**Files:** Create `backend/scripts/evaluate_centering.py`

- [ ] **Step 1: Write the harness**

Run centering over all 101 saved real scans. Report: how many produced a measurement, the
distribution of worst-axis values, and the distribution of PSA caps.

- [ ] **Step 2: Run it and sanity-check the output**

Real raw cards are usually *not* perfectly centred, so a plausible distribution is spread across
50–70% with a tail beyond. **If nearly every card reports 50/50, the measurement is not working** —
it is far more likely to be finding no border and defaulting than that a random handful of raw cards
are all gem-mint centred. Report the real distribution either way.

- [ ] **Step 3: Spot-check visually**

Export the 3 best- and 3 worst-centred crops with the measured border widths drawn on. Look at them
and confirm the lines sit on the real border edge. Paste what you found.

- [ ] **Step 4: Commit**

---

## Task 6: Record results and merge

- [ ] Update `PROJECT.md` and `AI_CONTEXT.md` with what Task 1 concluded and Task 5 measured, plus
      the explicit note that corners/edges/surface and grading EV remain blocked on data.
- [ ] Update the roadmap and `docs/index.html`.
- [ ] Merge and push.

---

## Definition of done

- [ ] Task 1 settled whether the 2.6% bias was real or a bug, and said which.
- [ ] Synthetic cards with known centering measure correctly to within 1.5%.
- [ ] `pytest` and the frontend build/tests pass.
- [ ] `evaluate_centering.py` reports a plausible distribution over the 101 real scans, visually
      spot-checked.
- [ ] The UI says centering *allows up to* a grade, and names the front-only and one-of-four caveats.
- [ ] Nothing anywhere claims an overall grade.

## What stays blocked after this

Corners, edges, surface, and grading EV all need data this project does not have: labelled graded
cards, and graded-card price history. Phase 3b should start by finding whether that data can be
sourced at all — that is a research question, not an engineering one, and the answer determines
whether a full grade predictor is buildable.
