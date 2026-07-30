# Phase 1c — Robust Card Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roughly double how often a real photo produces an answer — from 30% coverage to a measured 73% — without introducing a single confidently wrong identification.

**Architecture:** Replace the single brittle detector with a strategy chain. Each strategy proposes a card-shaped quad; every proposal is embedded (2.2 ms) and the crop with the best visual match wins. Add a manual corner-drag fallback for what still fails, and fix the accuracy metric that currently hides the real story.

**Tech Stack:** OpenCV, on the existing Python 3.12 / FastAPI backend and React PWA.

---

## Why this phase exists — measured, not assumed

Phase 1b put the app on a phone and scanned **99 real cards**. The result reframed the project:

| Status | scans | reviewed | correct |
|---|---|---|---|
| confident | 30 | 29 | **29 (100%)** |
| ambiguous | 13 | 10 | declined |
| **not_found** | **56** | — | — |

**Recognition is not the problem.** When the pipeline committed, it was right 29/29 — zero confident
errors on real photographs.

**Detection is the problem.** 57% of scans never found a card.

### Root cause, diagnosed on the real failures

Across 20 sampled failures, **no 4-point quad was found at all** (mean large-contour count 0.4). Not
a wrong shape being rejected by the aspect gate — nothing to reject. Successes had a median detected
aspect of 1.40, exactly a card. Brightness was near-identical between the groups (89 vs 96 of 255),
so it is not darkness.

Two compounding causes:

1. **Canny needs a gradient, not a level.** A light card border on a light background produces no
   closed edge contour. This is why a black background was required.
2. **`approxPolyDP` requires *exactly* 4 vertices.** Real card photos have rounded corners and
   sensor noise, so the polygon approximation frequently lands on 5–7 vertices and a perfectly
   visible card is discarded.

### What was measured to fix it

Candidate detectors run against all 56 real failures and all 30 real successes:

| strategy | recovers failures | keeps successes |
|---|---|---|
| canny (current) | 0 / 56 | 29 / 30 |
| otsu + polygon | 39 / 56 | 29 / 30 |
| adaptive + polygon | 56 / 56 | 29 / 30 |
| saturation | 3 / 56 | 3 / 30 |
| **otsu + minAreaRect** | **56 / 56** | **30 / 30** |

But "found a quad" is not "found the card" — the Phase 1a review caught rectification confidently
returning the card's interior artwork window at exactly the right size. So each detector's output was
run through the **full recognition pipeline**:

| | minAreaRect alone | **best-of-3 chain** |
|---|---|---|
| previously-failed → confident | 33 / 56 | **33 / 56** |
| previously-working → same card | 23 | **29** |
| **→ changed to a wrong card** | **0** | **0** |
| → lost | 6 | **0** |

`minAreaRect` alone regresses 6 working scans. **The chain regresses none.** Projected coverage:
**30% → 73%**, with zero confident errors either way.

The remaining 23 failures come back `ambiguous` rather than `not_found` — the crop is found but the
match is uncertain. Those are what the manual corner fallback (Task 4) is for.

---

## Scope

**In:** the detector chain, the accuracy metric fix, a manual-corner API path and UI, and a
re-measurement against the 99 saved scans.

**Out:** fine-tuning the encoder, sleeve-glare handling, and the OpenCV.js live overlay. Sleeved
cards were user-reported as inconsistent but have not been isolated as a distinct failure mode yet —
Task 6's re-measurement is what would justify a phase for it.

---

## File structure

```
backend/src/cardplatform/recognition/
  detectors.py     # NEW: named detection strategies, each proposing a quad
  rectify.py       # MODIFIED: find_card_corners keeps working; add detect_candidates
  service.py       # MODIFIED: pick the best-recognising crop
backend/src/cardplatform/scans/
  store.py         # MODIFIED: precision and coverage, not a blended accuracy
backend/src/cardplatform/
  api.py           # MODIFIED: accept manual corners on /recognize
backend/scripts/
  evaluate_detection.py   # NEW: replay the 99 saved scans through any detector set
frontend/src/
  components/CornerAdjust.tsx  # NEW: drag four corners over the captured photo
  App.tsx                      # MODIFIED: offer corner adjust after a failure
```

`detectors.py` holds pure functions with no I/O so each strategy can be tested against fixtures
independently, and the chain's selection logic can be tested without OpenCV behaviour in the way.

---

## Task 1: Detection strategies

**Files:**
- Create: `backend/src/cardplatform/recognition/detectors.py`
- Test: `backend/tests/test_detectors.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_detectors.py`:

```python
import cv2
import numpy as np
import pytest
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
    """The artwork window inside a card is ~0.65 — this is the guard that stopped
    rectification silently returning a stretched crop of the illustration."""
    quad = np.array([[0, 0], [350, 0], [350, 230], [0, 230]], dtype="float32")

    assert quad_is_card_shaped(quad, frame_area=700 * 900) is False


def test_quad_is_card_shaped_rejects_something_tiny():
    quad = np.array([[0, 0], [20, 0], [20, 28], [0, 28]], dtype="float32")

    assert quad_is_card_shaped(quad, frame_area=700 * 900) is False


def test_every_strategy_has_a_name():
    assert len(STRATEGIES) >= 3
    assert all(name and callable(fn) for name, fn in STRATEGIES)


def test_light_card_on_dark_background_is_detected():
    proposals = detect_candidates(_scene((225, 225, 220), 18))

    assert len(proposals) >= 1


def test_light_card_on_LIGHT_background_is_detected():
    """The measured real-world failure: 56 of 56 scans found no quad at all,
    because a light border on a light background forms no closed Canny contour."""
    proposals = detect_candidates(_scene((235, 232, 228), 205))

    assert len(proposals) >= 1, "no strategy handled a light-on-light scene"


def test_rotated_card_is_detected():
    proposals = detect_candidates(_scene((225, 225, 220), 18, angle=12))

    assert len(proposals) >= 1


def test_empty_frame_yields_no_proposals():
    blank = Image.fromarray(np.full((900, 700, 3), 18, dtype=np.uint8))

    assert detect_candidates(blank) == []


def test_proposals_are_named_and_deduplicated():
    proposals = detect_candidates(_scene((225, 225, 220), 18))

    names = [name for name, _ in proposals]
    assert len(names) == len(set(names)), "one proposal per strategy at most"
    for _, quad in proposals:
        assert quad.shape == (4, 2)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_detectors.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.detectors'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/detectors.py`:

```python
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
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# A card must occupy at least this fraction of the frame. Filters specular highlights
# and background clutter. Measured: detection works down to exactly 0.05 and hard-fails
# below it, which encodes a "fill the framing guide" assumption.
MIN_AREA_FRACTION = 0.05

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
    if cv2.contourArea(quad.astype(np.float32)) < frame_area * MIN_AREA_FRACTION:
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
    """The original strategy. Kept because it is the only one that held all 30 real
    successes when the others were tried alone."""
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


def detect_adaptive_rect(image: Image.Image) -> np.ndarray | None:
    """Local thresholding, for uneven lighting across the frame."""
    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (7, 7), 0),
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        8,
    )
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    return _largest_rotated_rect(closed, bgr.shape[0] * bgr.shape[1])


STRATEGIES: list[tuple[str, object]] = [
    ("canny", detect_canny),
    ("otsu_rect", detect_otsu_rect),
    ("adaptive_rect", detect_adaptive_rect),
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
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_detectors.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Prove the light-on-light test has teeth**

Temporarily reduce `STRATEGIES` to just `("canny", detect_canny)` and re-run. Expect
`test_light_card_on_LIGHT_background_is_detected` to **FAIL** — that is the exact real-world case,
and a chain that cannot demonstrate it is not earning its keep. Restore and confirm it passes. Paste
both outputs.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/recognition/detectors.py backend/tests/test_detectors.py && git commit -m "feat: add multi-strategy card detection"
```

---

## Task 2: Select the best-recognising crop

**Files:**
- Modify: `backend/src/cardplatform/recognition/rectify.py`
- Modify: `backend/src/cardplatform/recognition/service.py`
- Test: `backend/tests/test_recognition_service.py` (append)

The service currently rectifies once and recognises once. Now it rectifies every proposal, embeds
each (2.2 ms), and keeps the best. **OCR runs only on the winner** — it costs ~1 s, so running it per
proposal would triple scan time for no benefit.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_recognition_service.py`:

```python
import numpy as np
from PIL import Image

from cardplatform.recognition.types import Candidate


class ScriptedIndex:
    """Returns a different result per call, so proposal selection is observable."""

    def __init__(self, per_call):
        self.per_call = list(per_call)
        self.calls = 0

    def search(self, vector, top_k):
        result = self.per_call[min(self.calls, len(self.per_call) - 1)]
        self.calls += 1
        return list(result)[:top_k]


class CountingReader:
    def __init__(self, reading=None):
        from cardplatform.recognition.types import OcrReading

        self._reading = reading or OcrReading()
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return self._reading


def test_best_scoring_proposal_wins(seeded, monkeypatch):
    """Two detectors propose different crops; the one whose crop matches better wins."""
    from cardplatform.recognition import service as service_module

    quad_a = np.array([[0, 0], [100, 0], [100, 140], [0, 140]], dtype="float32")
    quad_b = np.array([[10, 10], [110, 10], [110, 150], [10, 150]], dtype="float32")
    monkeypatch.setattr(
        service_module, "detect_candidates", lambda image: [("a", quad_a), ("b", quad_b)]
    )

    index = ScriptedIndex(
        [
            (Candidate("base1-4", 0.60), Candidate("base4-4", 0.59)),  # weak
            (Candidate("me2pt5-114", 0.93), Candidate("me2pt5-252", 0.70)),  # strong
        ]
    )
    service = RecognitionService(
        session=seeded, encoder=FakeEncoder(), index=index, reader=FakeReader()
    )

    result = service.recognize(Image.new("RGB", (300, 400), (200, 40, 40)), rectify=True)

    assert result.card_id == "me2pt5-114"


def test_ocr_runs_once_not_per_proposal(seeded, monkeypatch):
    """OCR costs ~1s. Running it per proposal would triple scan time for nothing."""
    from cardplatform.recognition import service as service_module

    quad = np.array([[0, 0], [100, 0], [100, 140], [0, 140]], dtype="float32")
    monkeypatch.setattr(
        service_module, "detect_candidates", lambda image: [("a", quad), ("b", quad), ("c", quad)]
    )
    reader = CountingReader()
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=reader,
    )

    service.recognize(Image.new("RGB", (300, 400), (200, 40, 40)), rectify=True)

    assert reader.calls == 1


def test_no_proposals_is_not_found(seeded, monkeypatch):
    from cardplatform.recognition import service as service_module

    monkeypatch.setattr(service_module, "detect_candidates", lambda image: [])
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=FakeReader(),
    )

    result = service.recognize(Image.new("RGB", (300, 400), (18, 18, 18)), rectify=True)

    assert result.status == "not_found"


def test_manual_corners_bypass_detection(seeded, monkeypatch):
    """The fallback path: the user dragged the corners, so trust them."""
    from cardplatform.recognition import service as service_module

    monkeypatch.setattr(
        service_module, "detect_candidates", lambda image: pytest.fail("should not detect")
    )
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
    )

    result = service.recognize(
        Image.new("RGB", (300, 400), (200, 40, 40)),
        rectify=True,
        corners=[(0, 0), (100, 0), (100, 140), (0, 140)],
    )

    assert result.status == "confident"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_service.py -v
```

Expected: FAIL — `AttributeError: module 'cardplatform.recognition.service' has no attribute 'detect_candidates'`

- [ ] **Step 3: Point `rectify.py` at the shared helpers**

In `backend/src/cardplatform/recognition/rectify.py`, delete the local `order_corners`,
`_MIN_AREA_FRACTION`, `_MIN_ASPECT_RATIO`, `_MAX_ASPECT_RATIO`, and the aspect-gate logic inside
`find_card_corners`, and re-export from `detectors` instead so there is exactly one definition:

```python
from cardplatform.recognition.detectors import (  # noqa: F401  (re-exported)
    detect_canny,
    order_corners,
    quad_is_card_shaped,
)


def find_card_corners(image: Image.Image) -> np.ndarray | None:
    """Single-strategy detection, kept for callers that want the original behaviour."""
    return detect_canny(image)
```

Keep `rectify_from_corners` and `rectify_card` exactly as they are — `rectify_card` still calls
`find_card_corners`, so its existing tests continue to pass unchanged.

- [ ] **Step 4: Rewrite `RecognitionService.recognize`**

In `backend/src/cardplatform/recognition/service.py`, add the import:

```python
from cardplatform.recognition.detectors import detect_candidates
from cardplatform.recognition.rectify import rectify_from_corners
```

Replace `recognize` with:

```python
    def recognize(
        self,
        image: Image.Image,
        rectify: bool = True,
        corners: list[tuple[float, float]] | None = None,
    ) -> RecognitionResult:
        """Identify the card in `image`.

        `rectify=False` means the caller already produced a flat crop.
        `corners` means the user placed them by hand — trust that over any detector.

        When detecting, every strategy's proposal is embedded and the best-matching
        crop wins. Embedding costs 2.2 ms, so trying three is negligible; OCR costs
        about a second, so it runs only on the winner.
        """
        if not rectify:
            return self._recognize_crop(image)

        if corners is not None:
            crop = rectify_from_corners(
                image, np.array(corners, dtype="float32"), self.settings.rectified_size
            )
            return self._recognize_crop(crop)

        proposals = detect_candidates(image)
        if not proposals:
            logger.info("no card detected in frame by any strategy")
            return RecognitionResult(
                card_id=None,
                confidence=0.0,
                status="not_found",
                candidates=(),
                ocr=OcrReading(),
                visual_margin=0.0,
            )

        best_crop = None
        best_candidates: tuple = ()
        best_score = -1.0
        best_name = ""
        for name, quad in proposals:
            crop = rectify_from_corners(image, quad, self.settings.rectified_size)
            found = tuple(
                self.index.search(self.encoder.embed(crop), top_k=self.settings.visual_top_k)
            )
            score = found[0].visual_score if found else -1.0
            if score > best_score:
                best_score, best_crop, best_candidates, best_name = score, crop, found, name

        logger.info("detection strategy %r won with visual score %.3f", best_name, best_score)
        return self._fuse_for(best_crop, best_candidates)

    def _recognize_crop(self, crop: Image.Image) -> RecognitionResult:
        found = tuple(self.index.search(self.encoder.embed(crop), top_k=self.settings.visual_top_k))
        return self._fuse_for(crop, found)

    def _fuse_for(self, crop: Image.Image, found: tuple) -> RecognitionResult:
        catalog_numbers = self._collector_numbers([c.card_id for c in found])
        candidates = tuple(c for c in found if c.card_id in catalog_numbers)
        reading = self.reader.read(crop)
        return fuse(candidates, reading, catalog_numbers, config=self.fusion_config)
```

Add `import numpy as np` to the imports.

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_service.py backend/tests/test_rectify.py -v
```

Expected: all pass. The existing `test_rectify.py` must be untouched and still green — if it is not,
`rectify_card` behaviour changed and that is a regression, not a test to update.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/recognition/rectify.py backend/src/cardplatform/recognition/service.py backend/tests/test_recognition_service.py && git commit -m "feat: pick the best-recognising crop across detection strategies"
```

---

## Task 3: Report precision and coverage, not a blended accuracy

**Files:**
- Modify: `backend/src/cardplatform/scans/store.py`
- Modify: `backend/src/cardplatform/api.py`
- Test: `backend/tests/test_scan_store.py` (append), `backend/tests/test_scan_api.py` (append)

`accuracy()` currently counts an `ambiguous` result the user resolved as **wrong** — but the pipeline
made no prediction to be wrong about. That conflates *declining to guess* with *guessing wrong*,
which are opposites here. It reported 74.4% for a system that was actually right 29 out of 29.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scan_store.py`:

```python
def test_precision_counts_only_scans_that_made_a_prediction(db, tmp_path):
    """An ambiguous scan made no claim, so it can be neither right nor wrong."""
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    right = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    wrong = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    amb = store.record(image_bytes=_png(), predicted_card_id=None, status="ambiguous")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    store.confirm(right.id)
    store.correct(wrong.id, "base4-4")
    store.correct(amb.id, "base4-4")

    stats = store.accuracy()
    assert stats.predicted == 2
    assert stats.correct == 1
    assert stats.precision == pytest.approx(0.5)


def test_coverage_is_answers_over_all_scans(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    store.record(image_bytes=_png(), predicted_card_id=None, status="ambiguous")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    stats = store.accuracy()
    assert stats.total == 4
    assert stats.answered == 1
    assert stats.coverage == pytest.approx(0.25)


def test_status_breakdown_is_reported(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    assert store.accuracy().by_status == {"confident": 1, "not_found": 2}


def test_precision_with_nothing_predicted_is_zero_not_a_crash(db, tmp_path):
    _seed(db)
    stats = ScanStore(db, Settings(data_dir=tmp_path)).accuracy()

    assert stats.predicted == 0
    assert stats.precision == 0.0
    assert stats.coverage == 0.0
```

- [ ] **Step 2: Run it to verify it fails**

Expected: FAIL — `AttributeError: 'ScanAccuracy' object has no attribute 'predicted'`

- [ ] **Step 3: Rewrite the metric**

In `backend/src/cardplatform/scans/store.py`, replace `ScanAccuracy` and `accuracy`:

```python
@dataclass(frozen=True)
class ScanAccuracy:
    """Precision and coverage, reported separately and deliberately.

    A blended "accuracy" counts a declined `ambiguous` result as a wrong answer, which
    conflates refusing to guess with guessing wrong. Measured over 99 real scans that
    blend read 74.4% for a pipeline that was right 29 out of 29 when it committed.
    """

    total: int
    answered: int
    predicted: int
    correct: int
    precision: float
    coverage: float
    by_status: dict[str, int]


class ScanStore:
    ...

    def accuracy(self) -> ScanAccuracy:
        rows = list(self.session.scalars(select(ScanLog)).all())
        by_status: dict[str, int] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1

        answered = [r for r in rows if r.predicted_card_id is not None]
        # Only reviewed predictions are evidence; an unreviewed one is neither.
        predicted = [r for r in answered if r.confirmed]
        correct = [r for r in predicted if r.corrected_card_id is None]

        return ScanAccuracy(
            total=len(rows),
            answered=len(answered),
            predicted=len(predicted),
            correct=len(correct),
            precision=len(correct) / len(predicted) if predicted else 0.0,
            coverage=len(answered) / len(rows) if rows else 0.0,
            by_status=by_status,
        )
```

- [ ] **Step 4: Update the API model**

In `backend/src/cardplatform/api.py`, replace `ScanAccuracyOut`:

```python
class ScanAccuracyOut(BaseModel):
    total: int
    answered: int
    predicted: int
    correct: int
    precision: float
    coverage: float
    by_status: dict[str, int]
```

and update the `scan_accuracy` endpoint to pass every field through.

Append to `backend/tests/test_scan_api.py`:

```python
def test_accuracy_endpoint_reports_precision_and_coverage(client):
    right = _record(client).json()["id"]
    wrong = _record(client).json()["id"]
    _record(client, status="not_found", predicted=None)

    client.post(f"/scans/{right}/confirm")
    client.post(f"/scans/{wrong}/correct", params={"card_id": "base4-4"})

    body = client.get("/scans/accuracy").json()
    assert body["total"] == 3
    assert body["answered"] == 2
    assert body["precision"] == 0.5
    assert body["coverage"] == pytest.approx(2 / 3)
    assert body["by_status"]["not_found"] == 1
```

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_scan_store.py backend/tests/test_scan_api.py -v
```

Expected: all pass. **The old `test_accuracy_counts_only_reviewed_scans` and
`test_accuracy_reports_reviewed_scans_only` assert the removed fields — delete them, and say so in
your report.** They encode the metric being replaced.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/scans/store.py backend/src/cardplatform/api.py backend/tests/test_scan_store.py backend/tests/test_scan_api.py && git commit -m "fix: report precision and coverage separately"
```

---

## Task 4: Manual corner adjustment

**Files:**
- Modify: `backend/src/cardplatform/api.py`
- Create: `frontend/src/components/CornerAdjust.tsx`
- Modify: `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/styles.css`
- Test: `backend/tests/test_recognize_api.py` (append)

23 of the 56 recovered scans still come back `ambiguous`. Rather than leave the user stuck, let them
drag the four corners themselves — the design spec anticipated exactly this fallback.

- [ ] **Step 1: Write the failing API test**

Append to `backend/tests/test_recognize_api.py`:

```python
def test_manual_corners_are_passed_to_the_service(seeded):
    result = RecognitionResult(
        card_id="base1-4",
        confidence=0.97,
        status="confident",
        candidates=(Candidate("base1-4", 0.91),),
        ocr=OcrReading(),
        visual_margin=0.2,
    )

    class CornerStub:
        def __init__(self):
            self.corners = "unset"

        def recognize(self, image, rectify=True, corners=None):
            self.corners = corners
            return result

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    stub = CornerStub()
    app.dependency_overrides[get_recognition_service] = lambda: stub
    client = TestClient(app)

    response = client.post(
        "/recognize",
        params={"corners": "10,20,110,20,110,160,10,160"},
        files={"file": ("c.png", _png(), "image/png")},
    )

    assert response.status_code == 200
    assert stub.corners == [(10.0, 20.0), (110.0, 20.0), (110.0, 160.0), (10.0, 160.0)]


def test_malformed_corners_are_rejected(seeded):
    result = RecognitionResult(None, 0.0, "not_found", (), OcrReading(), 0.0)
    client, _ = _client(seeded, result)

    response = client.post(
        "/recognize", params={"corners": "1,2,3"}, files={"file": ("c.png", _png(), "image/png")}
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run it, confirm it fails**

Expected: FAIL — the endpoint ignores `corners`, so `stub.corners` stays `"unset"`.

- [ ] **Step 3: Accept corners on the endpoint**

In `backend/src/cardplatform/api.py`, add a parser next to the other helpers:

```python
def _parse_corners(raw: str | None) -> list[tuple[float, float]] | None:
    """Parse "x1,y1,x2,y2,x3,y3,x4,y4" from the manual-adjust UI."""
    if not raw:
        return None
    try:
        values = [float(part) for part in raw.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="corners must be numbers") from exc
    if len(values) != 8:
        raise HTTPException(status_code=422, detail="corners must be 8 numbers")
    return [(values[i], values[i + 1]) for i in range(0, 8, 2)]
```

Add `corners: str | None = Query(default=None)` to the `/recognize` signature and pass
`corners=_parse_corners(corners)` into `service.recognize(...)`.

- [ ] **Step 4: Add the client call**

In `frontend/src/api/client.ts`, extend `recognize`'s options with `corners?: [number, number][]`
and append it to the query string when present:

```ts
  if (options.corners) {
    params.set("corners", options.corners.flat().join(","));
  }
```

- [ ] **Step 5: Write the corner-drag component**

`frontend/src/components/CornerAdjust.tsx`:

```tsx
import { useCallback, useRef, useState } from "react";

type Point = [number, number];

interface Props {
  image: Blob;
  onSubmit: (corners: Point[]) => void;
  onCancel: () => void;
}

export default function CornerAdjust({ image, onSubmit, onCancel }: Props) {
  const url = useRef(URL.createObjectURL(image)).current;
  const boxRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  // Fractions of the displayed image, so they survive any rescaling.
  const [points, setPoints] = useState<Point[]>([
    [0.2, 0.15],
    [0.8, 0.15],
    [0.8, 0.85],
    [0.2, 0.85],
  ]);
  const dragging = useRef<number | null>(null);

  const move = useCallback((event: React.PointerEvent) => {
    const index = dragging.current;
    const box = boxRef.current;
    if (index === null || !box) return;
    const rect = box.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    setPoints((prev) => prev.map((p, i) => (i === index ? [x, y] : p)));
  }, []);

  const submit = useCallback(() => {
    if (!natural) return;
    // Convert back to source-image pixels — the server rectifies against the original.
    onSubmit(points.map(([x, y]) => [x * natural.w, y * natural.h] as Point));
  }, [natural, points, onSubmit]);

  return (
    <div className="corner-adjust">
      <p className="hint">Drag the four dots to the card's corners.</p>
      <div
        ref={boxRef}
        className="corner-box"
        onPointerMove={move}
        onPointerUp={() => (dragging.current = null)}
        onPointerLeave={() => (dragging.current = null)}
      >
        <img
          src={url}
          alt=""
          onLoad={(e) =>
            setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
          }
        />
        <svg className="corner-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon
            points={points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ")}
            fill="rgba(255,203,5,0.15)"
            stroke="var(--accent)"
            strokeWidth="0.6"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        {points.map(([x, y], i) => (
          <button
            key={i}
            className="handle"
            style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
            onPointerDown={(e) => {
              dragging.current = i;
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            aria-label={`Corner ${i + 1}`}
          />
        ))}
      </div>
      <div className="actions">
        <button className="primary" onClick={submit} disabled={!natural}>
          Use these corners
        </button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
```

Append to `frontend/src/styles.css`:

```css
.corner-box { position: relative; touch-action: none; user-select: none; }
.corner-box img { width: 100%; display: block; border-radius: 10px; }
.corner-overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.handle {
  position: absolute;
  width: 30px;
  height: 30px;
  margin: -15px 0 0 -15px;
  border-radius: 50%;
  border: 2px solid #1a1500;
  background: var(--accent);
  padding: 0;
  touch-action: none;
}
.corner-adjust .hint { color: var(--fg-dim); font-size: 0.9rem; }
```

- [ ] **Step 6: Offer it after a failure**

In `frontend/src/App.tsx`, keep the captured `Blob` in state. When the result is `not_found` or
`ambiguous`, render a button that switches to `CornerAdjust`; on submit, call `recognize` again with
the corners and the same blob, then re-record the scan.

- [ ] **Step 7: Verify**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest -q
npm --prefix C:\ClaudeKnowledge\frontend run build
npm --prefix C:\ClaudeKnowledge\frontend test
```

Expected: backend green, frontend builds clean, frontend tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/cardplatform/api.py backend/tests/test_recognize_api.py frontend/src && git commit -m "feat: add manual corner adjustment fallback"
```

---

## Task 5: Replay harness over the saved scans

**Files:**
- Create: `backend/scripts/evaluate_detection.py`

- [ ] **Step 1: Write the harness**

`backend/scripts/evaluate_detection.py`:

```python
"""Replays every saved scan through the current pipeline and reports the change.

Phase 1b left 99 real photographs in data/scans/ with the outcome each one produced.
That is a fixed regression suite for detection: any change here can be scored against
real inputs rather than argued about.
"""

import sys
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from cardplatform.db.models import ScanLog
from cardplatform.db.session import Database
from cardplatform.recognition.encoder import CardEncoder
from cardplatform.recognition.index import CardIndex
from cardplatform.recognition.ocr import CollectorNumberReader
from cardplatform.recognition.service import RecognitionService


def main() -> int:
    database = Database()
    encoder = CardEncoder(database.settings)
    index = CardIndex(database.settings).load()
    reader = CollectorNumberReader()
    print(f"index: {index.size} cards\n")

    with database.session() as session:
        rows = session.scalars(select(ScanLog).order_by(ScanLog.id)).all()
        records = [(r.image_path, r.status, r.predicted_card_id, r.corrected_card_id) for r in rows]

        service = RecognitionService(
            session=session, encoder=encoder, index=index, reader=reader
        )

        moved = {"gained": 0, "same": 0, "lost": 0, "changed": 0}
        now_status: dict[str, int] = {}
        for path, was_status, was_card, corrected in records:
            file = database.settings.data_dir / path
            if not file.exists():
                continue
            result = service.recognize(Image.open(file).convert("RGB"), rectify=True)
            now_status[result.status] = now_status.get(result.status, 0) + 1

            truth = corrected or was_card
            if was_status != "confident" and result.status == "confident":
                moved["gained"] += 1
            elif was_status == "confident" and result.status != "confident":
                moved["lost"] += 1
            elif was_status == "confident" and result.card_id == truth:
                moved["same"] += 1
            elif was_status == "confident" and result.card_id != truth:
                moved["changed"] += 1
                print(f"  REGRESSION {path}: {truth} -> {result.card_id}")

    total = sum(now_status.values())
    print(f"\n{'status':<12}{'now':>6}")
    print("-" * 20)
    for status, count in sorted(now_status.items(), key=lambda kv: -kv[1]):
        print(f"{status:<12}{count:>6}")

    confident = now_status.get("confident", 0)
    print(f"\ncoverage: {confident}/{total} = {confident / total * 100:.0f}%  (baseline 30%)")
    print(f"gained {moved['gained']}, lost {moved['lost']}, unchanged {moved['same']}")
    print(f"REGRESSIONS (confident but now a different card): {moved['changed']}")
    if moved["changed"]:
        print("\nAny regression is a failure — a confidently wrong card is the worst outcome.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe backend/scripts/evaluate_detection.py
```

**Expected from the spike: coverage rises from 30% toward ~73%, with 0 regressions.** Paste the real
output. If regressions appear, stop and report — the chain is supposed to be strictly safe, and a
confident wrong answer is worse than a missed detection.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/evaluate_detection.py && git commit -m "feat: add detection replay harness over saved scans"
```

---

## Task 6: Record results and merge

**Files:** Modify `PROJECT.md`, `docs/index.html`, `CLAUDE.md`

- [ ] **Step 1:** Add a "Phase 1c — shipped" section to `PROJECT.md` with the **real** coverage and
  regression numbers from Task 5, not the projected ones.
- [ ] **Step 2:** Mark Phase 1c complete in the roadmap and on the site.
- [ ] **Step 3:** In `CLAUDE.md`, replace the note claiming Canny needs a black background with what
  actually replaced it, and add: *"Detection proposals are selected by which crop recognises best,
  not by which strategy ran first."*
- [ ] **Step 4:** Merge and push.

---

## Definition of done

- [ ] `pytest` passes; `npm test` and `npm run build` pass.
- [ ] `evaluate_detection.py` reports coverage well above the 30% baseline with **0 regressions**.
- [ ] A light card on a light background is detected — the exact case that failed 56 times.
- [ ] Manual corner adjustment recovers a scan that automatic detection could not.
- [ ] `/scans/accuracy` reports precision and coverage separately.

## What this does not fix

Around 23 of the recovered scans still land on `ambiguous` — detected, but not matched confidently.
That is a recognition-quality problem, not a detection one, and the honest next lever is fine-tuning
the encoder on the corrected scans this project has been collecting since Phase 1b. Sleeve glare is
also unresolved and unquantified; Task 5's replay is what would isolate it.
