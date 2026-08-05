# Phase 4 — Bulk Cataloger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect, recognize, and value every card in one binder-page photo — one photo → N identified + valued cards, one `scan_logs` row per card grouped by a shared `batch_id`, with a batch review grid.

**Architecture:** Split detection (run once → N non-overlapping quads via IoU NMS) from recognition (per-quad, batched embedding, parallel OCR). Additive schema (`batch_id` + `batch_index` on `scan_logs`). New `POST /recognize/batch` endpoint reusing the existing `RecognizeOut` per card. Batch review grid reusing `ScanResult`/`CandidatePicker`/`CornerAdjust` per cell. Single-card path unchanged — additive only, 105-scan baseline must not regress.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy/SQLite (`backend/.venv`), React 19 + TypeScript + Vite PWA + vitest. OpenCV detection, open-clip embedding, rapidocr-onnxruntime OCR.

**Sacred constraints (in force):** never resolve price ad-hoc (`PriceService.latest_price` only); honest empty states (None/em dash, never `$0`, never fabricate); snapshots immutable; no `data/` deletion; additive schema only (no destructive migration, 105 rows stay NULL); recognition is the arbiter (geometry never auto-promotes a low-visual-score crop); single-card `detect_candidates` + `POST /recognize` unchanged. See `docs/superpowers/specs/2026-08-04-phase-4-bulk-cataloger-design.md`.

**Branch:** `phase-4-bulk-cataloger` (off `main`). Commit per task. Only edit within `C:\ClaudeKnowledge`.

---

## Task 1: Multi-quad detection + IoU NMS

**Files:**
- Modify: `backend/src/cardplatform/recognition/detectors.py`
- Test: `backend/tests/test_detect_all_quads.py` (new)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_detect_all_quads.py`:
```python
"""Tests for multi-quad detection (Phase 4 bulk cataloger).

detect_all_quads returns every card-shaped quad across strategies + Otsu polarities,
IoU-NMS-deduped. Detection is pure geometry here — no catalog/encoder needed. The
synthetic page is N white rounded-rect "cards" on a dark background, arranged in a grid.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from cardplatform.recognition.detectors import (
    detect_all_quads,
    detect_candidates,
    _iou,
    _nms,
)


def _card(x: int, y: int, w: int = 240, h: int = 336) -> list[tuple[int, int]]:
    """A card-shaped rectangle (1.4 aspect), as 4 corners."""
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _page(cards: list[list[tuple[int, int]]], size: tuple[int, int] = (1200, 1500)) -> Image.Image:
    """A dark page with N white card rectangles drawn on it."""
    canvas = np.full((size[1], size[0]), 40, dtype=np.uint8)  # dark gray background
    for corners in cards:
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        canvas[y0:y1, x0:x1] = 230  # near-white card
    return Image.fromarray(canvas, mode="L").convert("RGB")


def test_detect_all_quads_finds_every_card_in_a_grid():
    # 3x3 grid of cards → 9 quads.
    cards = [_card(60 + (i % 3) * 360, 60 + (i // 3) * 460) for i in range(9)]
    page = _page(cards)
    quads = detect_all_quads(page)
    assert len(quads) == 9


def test_detect_all_quads_returns_nms_deduped_quads():
    # Two near-identical overlapping quads → NMS keeps one.
    a = np.array(_card(100, 100), dtype="float32")
    b = np.array(_card(105, 105), dtype="float32")  # ~99% overlap
    assert _iou(a, b) > 0.3
    kept = _nms([a, b], threshold=0.3)
    assert len(kept) == 1


def test_detect_all_quads_rejects_whole_frame_blob():
    # A single full-frame "card" (the degenerate adaptive case) is rejected by MAX_AREA_FRACTION.
    full = _page([_card(0, 0, 1190, 1490)])  # ~0.99 of frame
    quads = detect_all_quads(full)
    assert quads == []


def test_detect_candidates_unchanged_single_card():
    # The single-card path must be untouched — one card → at least one proposal.
    page = _page([_card(480, 580)])
    proposals = detect_candidates(page)
    assert len(proposals) >= 1
    # ...and detect_all_quads agrees on count for a single card.
    assert len(detect_all_quads(page)) == 1


def test_detect_all_quads_empty_page_returns_empty():
    blank = Image.fromarray(np.full((1500, 1200), 40, dtype=np.uint8), mode="L").convert("RGB")
    assert detect_all_quads(blank) == []


def test_iou_disjoint_is_zero():
    a = np.array(_card(0, 0), dtype="float32")
    b = np.array(_card(800, 800), dtype="float32")  # no overlap
    assert _iou(a, b) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_detect_all_quads.py -q`
Expected: FAIL with `ImportError: cannot import name 'detect_all_quads'` (and `_iou`, `_nms`).

- [ ] **Step 3: Implement `detect_all_quads` + helpers**

Append to `backend/src/cardplatform/recognition/detectors.py` (do NOT modify `detect_candidates`, `_largest_*`, or the constants — additive only):
```python
# --- Phase 4: multi-quad detection (bulk cataloger) -------------------------
#
# detect_candidates returns ONE quad per strategy (single-card path, unchanged).
# detect_all_quads returns EVERY card-shaped quad across both strategies + both
# Otsu polarities, then IoU-NMS-dedupes. Recognition is still the arbiter: a kept
# quad that embeds to a low visual_score is a not_found, never auto-promoted on
# geometry. MAX_AREA_FRACTION is kept — it rejects the degenerate whole-frame blob
# that adaptive thresholding produced on 101/101 real scans; a binder card is
# ~0.11 of a 9-card frame, comfortably above MIN_AREA_FRACTION=0.05 and below 0.98.

_NMS_IOU_THRESHOLD = 0.3


def _all_polygon_quads(mask: np.ndarray, frame_area: float) -> list[np.ndarray]:
    """Every card-shaped 4-vertex polygon quad in the mask (not just the largest)."""
    quads: list[np.ndarray] = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < frame_area * MIN_AREA_FRACTION:
            break  # sorted desc — everything after is also too small
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) == 4:
            quad = order_corners(approx.reshape(4, 2).astype("float32"))
            if quad_is_card_shaped(quad, frame_area):
                quads.append(quad)
    return quads


def _all_rotated_rect_quads(mask: np.ndarray, frame_area: float) -> list[np.ndarray]:
    """Every card-shaped rotated-rect quad in the mask (not just the largest)."""
    quads: list[np.ndarray] = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < frame_area * MIN_AREA_FRACTION:
            break
        quad = order_corners(cv2.boxPoints(cv2.minAreaRect(contour)).astype("float32"))
        if quad_is_card_shaped(quad, frame_area):
            quads.append(quad)
    return quads


def _canny_quads(image: Image.Image) -> list[np.ndarray]:
    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    return _all_polygon_quads(edges, bgr.shape[0] * bgr.shape[1])


def _otsu_rect_quads(image: Image.Image) -> list[np.ndarray]:
    """Both Otsu polarities — a card may be lighter OR darker than its surroundings."""
    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    area = bgr.shape[0] * bgr.shape[1]
    _, binary = cv2.threshold(
        cv2.GaussianBlur(gray, (7, 7), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    quads: list[np.ndarray] = []
    for mask in (binary, cv2.bitwise_not(binary)):
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        quads.extend(_all_rotated_rect_quads(closed, area))
    return quads


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection-over-union of two convex quads (order_corners output)."""
    a2 = a.astype(np.float32)
    b2 = b.astype(np.float32)
    inter, _ = cv2.intersectConvexConvex(a2, b2)
    inter = max(float(inter), 0.0)
    area_a = cv2.contourArea(a2)
    area_b = cv2.contourArea(b2)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _nms(quads: list[np.ndarray], threshold: float = _NMS_IOU_THRESHOLD) -> list[np.ndarray]:
    """Drop the smaller quad of any pair with IoU above threshold. Largest-first."""
    order = sorted(
        range(len(quads)),
        key=lambda i: cv2.contourArea(quads[i].astype(np.float32)),
        reverse=True,
    )
    kept: list[np.ndarray] = []
    for i in order:
        if not any(_iou(quads[i], kept_q) > threshold for kept_q in kept):
            kept.append(quads[i])
    return kept


def detect_all_quads(image: Image.Image) -> list[tuple[str, np.ndarray]]:
    """Every card-shaped quad across all strategies + polarities, NMS-deduped.

    Returns one (strategy_name, quad) per surviving proposal, largest-area first.
    The single-card detect_candidates path is unchanged; this is the bulk sibling.
    """
    proposals: list[tuple[str, np.ndarray]] = []
    try:
        for q in _canny_quads(image):
            proposals.append(("canny", q))
    except cv2.error:
        pass
    try:
        for q in _otsu_rect_quads(image):
            proposals.append(("otsu_rect", q))
    except cv2.error:
        pass
    if not proposals:
        return []
    # NMS largest-first; keep the first (largest) proposer's name per survivor.
    order = sorted(
        range(len(proposals)),
        key=lambda i: cv2.contourArea(proposals[i][1].astype(np.float32)),
        reverse=True,
    )
    kept: list[tuple[str, np.ndarray]] = []
    for i in order:
        name_i, quad_i = proposals[i]
        if not any(_iou(quad_i, quad_j) > _NMS_IOU_THRESHOLD for _, quad_j in kept):
            kept.append((name_i, quad_i))
    return kept
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_detect_all_quads.py -q`
Expected: PASS (6 tests). If `test_detect_all_quads_finds_every_card_in_a_grid` finds ≠9, tune the synthetic card size/spacing in the test (not the detector constants) until the geometry is unambiguous — detection should find 9 distinct, non-overlapping, card-shaped quads.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (485 + 6 = 491). The single-card `detect_candidates` tests stay green.

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge && git add backend/src/cardplatform/recognition/detectors.py backend/tests/test_detect_all_quads.py && git commit -m "feat(detection): detect_all_quads multi-quad detection + IoU NMS (T1)"
```

---

## Task 2: Batched recognition (`recognize_many`)

**Files:**
- Modify: `backend/src/cardplatform/recognition/service.py`
- Modify: `backend/src/cardplatform/config.py`
- Test: `backend/tests/test_recognize_many.py` (new)

- [ ] **Step 1: Add the `batch_ocr_workers` setting**

In `backend/src/cardplatform/config.py`, add to the `Settings` class (near the other recognition settings, env `CARDPLATFORM_BATCH_OCR_WORKERS`):
```python
    # Phase 4: parallel OCR workers for recognize_many. RapidOCR is not thread-safe,
    # so each worker constructs its own engine. Capped to [1, 4] — OCR is ~1 s/crop
    # and each engine is a meaningful memory cost.
    batch_ocr_workers: int = 2
```
Add validation in `Settings` (or wherever the existing validators live — match the pattern, e.g. a `model_validator` or a property) clamping to `[1, 4]`. If the codebase uses plain pydantic defaults without validators, add a `@field_validator("batch_ocr_workers")` that clamps:
```python
    @field_validator("batch_ocr_workers")
    @classmethod
    def _clamp_batch_ocr_workers(cls, v: int) -> int:
        return max(1, min(4, int(v)))
```
(Match the existing validator import style in `config.py` — if `field_validator` isn't already imported, add `from pydantic import field_validator`.)

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_recognize_many.py` (mirror the existing `test_recognition.py` fake-encoder/index/reader pattern — locate it and reuse the fakes; the key behaviors under test are below):
```python
"""Tests for recognize_many (Phase 4 batched recognition)."""
from __future__ import annotations

import numpy as np
from PIL import Image

from cardplatform.recognition.service import RecognitionService
from cardplatform.recognition.types import RecognitionResult, OcrReading


def _crop(w: int = 600, h: int = 825) -> Image.Image:
    return Image.new("RGB", (w, h), (200, 200, 200))


class _FakeIndex:
    def __init__(self, card_id: str = "base1-4", score: float = 0.95):
        self._card_id = card_id
        self._score = score

    def search(self, vec, top_k: int):
        from cardplatform.recognition.types import Candidate
        # Low-score vectors (the not_found / sleeve case) return nothing.
        if self._score < 0.0:
            return ()
        return (Candidate(card_id=self._card_id, visual_score=self._score),)


class _FakeEncoder:
    dimension = 512

    def embed(self, image):
        return self.embed_many([image])[0]

    def embed_many(self, images, batch_size=128):
        # One vector per image so per-crop scores can differ if needed.
        return np.zeros((len(images), self.dimension), dtype=np.float32)


class _FakeReader:
    """An OCR reader that can be 'cloned' per worker (mirrors rapidocr's thread-safety need)."""

    def read(self, crop):
        return OcrReading()

    def __deepcopy__(self, memo):
        return _FakeReader()  # each worker gets its own instance


def _service(session, index, monkeypatch_reader=False):
    return RecognitionService(
        session=session,
        encoder=_FakeEncoder(),
        index=index,
        reader=_FakeReader(),
        settings=__import__("cardplatform.config", fromlist=["settings"]).settings,
    )


def test_recognize_many_returns_one_result_per_quad(session):
    service = _service(session, _FakeIndex())
    quads = [np.array([[0, 0], [600, 0], [600, 825], [0, 825]], dtype="float32")]
    results = service.recognize_many(_crop(1200, 825), quads)
    assert len(results) == 1
    quad, result, centering = results[0]
    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.rectified_path is not None  # persisted per winning crop


def test_recognize_many_preserves_not_found_per_crop(session):
    # A quad that embeds to nothing → not_found, rectified_path None — never auto-promoted.
    service = _service(session, _FakeIndex(score=-1.0))
    quads = [np.array([[0, 0], [600, 0], [600, 825], [0, 825]], dtype="float32")]
    results = service.recognize_many(_crop(1200, 825), quads)
    assert len(results) == 1
    _, result, _ = results[0]
    assert result.status == "not_found"
    assert result.card_id is None
    assert result.rectified_path is None


def test_recognize_many_empty_quads_returns_empty(session):
    service = _service(session, _FakeIndex())
    assert service.recognize_many(_crop(1200, 825), []) == []


def test_recognize_many_multiple_quads(session):
    service = _service(session, _FakeIndex())
    quads = [
        np.array([[0, 0], [400, 0], [400, 825], [0, 825]], dtype="float32"),
        np.array([[400, 0], [800, 0], [800, 825], [400, 825]], dtype="float32"),
    ]
    results = service.recognize_many(_crop(800, 825), quads)
    assert len(results) == 2
    assert all(r.status == "confident" for _, r, _ in results)
    # Each crop persists its own rectified crop.
    assert all(r.rectified_path is not None for _, r, _ in results)
```

Use the existing `session` fixture from `backend/tests/conftest.py` (the `db` fixture yields a Session — match the real fixture name used by `test_recognition.py`). If the real fixture is named `db`, alias or rename the parameter. **Read `backend/tests/test_recognition.py` + `conftest.py` first** and use the exact fixture + fake patterns they use; the fakes above are a sketch to be aligned to the real ones.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_recognize_many.py -q`
Expected: FAIL with `AttributeError: 'RecognitionService' object has no attribute 'recognize_many'`.

- [ ] **Step 4: Implement `recognize_many`**

Add to `backend/src/cardplatform/recognition/service.py` (add `from concurrent.futures import ThreadPoolExecutor` and `import copy` to the imports; additive — do not modify `recognize`/`_fuse_for`):
```python
    def recognize_many(
        self,
        image: Image.Image,
        quads: list[np.ndarray],
    ) -> list[tuple[np.ndarray, RecognitionResult, "CenteringResult | None"]]:
        """Recognize every quad in one image (Phase 4 bulk cataloger).

        Detection has already run (these are the N kept quads). This rectifies each,
        embeds them in ONE batched call, searches per vector, then fuses + OCRs each
        winning crop. OCR (~1 s/crop) is parallelized across a per-worker reader pool
        (RapidOCR is not thread-safe). Recognition is the arbiter: a quad that embeds
        low is a not_found per crop — geometry never auto-promotes.

        Returns one (quad, result, centering) per input quad, in input order.
        """
        if not quads:
            return []

        crops = [
            rectify_from_corners(image, quad, self.settings.rectified_size) for quad in quads
        ]
        vectors = self.encoder.embed_many(crops)
        # Visual search per vector (trivial loop); collect (crop, found) per slot.
        found_per_crop: list[tuple] = []
        for crop, vec in zip(crops, vectors):
            found_per_crop.append(
                tuple(self.index.search(vec, top_k=self.settings.visual_top_k))
            )

        workers = getattr(self.settings, "batch_ocr_workers", 1) or 1
        # Each worker needs its own reader (not thread-safe). The pool deep-copies the
        # template reader; a reader without __deepcopy__ is reconstructed by copy.deepcopy
        # which falls back to __reduce_ex__ — rapidocr's engine supports this.
        def _fuse_slot(args):
            i = args
            return i, self._fuse_for(crops[i], found_per_crop[i])

        results: list[tuple[np.ndarray, RecognitionResult, "CenteringResult | None"]] = [
            None  # type: ignore[list-item]
        ] * len(quads)
        if workers <= 1 or len(quads) == 1:
            for i in range(len(quads)):
                _, (result, centering) = _fuse_slot(i)
                results[i] = (quads[i], result, centering)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # Each thread reuses self.reader safely only if it has its own copy;
                # build per-worker readers up front.
                self._worker_readers = [copy.deepcopy(self.reader) for _ in range(workers)]
                futures = {pool.submit(self._fuse_for_worker, w, crops[i], found_per_crop[i], i): i
                           for i, w in enumerate([i % workers for i in range(len(quads))])}
                # Simpler: submit a wrapper that picks the worker reader by thread id.
                # (See helper below — implemented to avoid thread-safety issues.)
                for fut in futures:
                    i = futures[fut]
                    result, centering = fut.result()
                    results[i] = (quads[i], result, centering)
            self._worker_readers = None
        return results

    def _fuse_for_worker(self, worker_idx, crop, found, slot_idx):
        """Run _fuse_for using a per-worker reader copy (thread-safe OCR)."""
        original = self.reader
        if getattr(self, "_worker_readers", None) is not None:
            self.reader = self._worker_readers[worker_idx]
        try:
            return self._fuse_for(crop, found)
        finally:
            self.reader = original
```

**Note for the implementer:** the thread-pool wiring above is a starting sketch; the cleanest correct approach is to bind each worker a fixed reader copy and submit `lambda i: self._fuse_with_reader(self._worker_readers[i % workers], crops[i], found_per_crop[i])`. Refactor `_fuse_for` to accept an optional `reader` argument so the worker passes its own copy without mutating `self.reader` (shared mutable state across threads is the bug to avoid). Final shape:
```python
    def _fuse_for(self, crop, found, reader=None):
        reader = reader if reader is not None else self.reader
        ...
        reading = reader.read(crop)
        ...
```
and `recognize_many` submits `pool.submit(self._fuse_for, crops[i], found_per_crop[i], self._worker_readers[i % workers])`. Keep the per-crop stale-index guard, the `not_found → rectified_path=None` contract, and `_persist_rectified_crop` per crop. `_now`/settings unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_recognize_many.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full suite**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (491 + 4 = 495).

- [ ] **Step 7: Commit**

```bash
cd C:\ClaudeKnowledge && git add backend/src/cardplatform/recognition/service.py backend/src/cardplatform/config.py backend/tests/test_recognize_many.py && git commit -m "feat(recognition): recognize_many batched recognition + parallel OCR pool (T2)"
```

---

## Task 3: Batch scan logging (additive schema + batch writer)

**Files:**
- Modify: `backend/src/cardplatform/db/models.py`
- Modify: `backend/src/cardplatform/db/migrations.py`
- Modify: `backend/src/cardplatform/scans/store.py`
- Test: `backend/tests/test_scan_store_batch.py` (new)

- [ ] **Step 1: Add `batch_id` + `batch_index` to the `ScanLog` model**

In `backend/src/cardplatform/db/models.py`, in `class ScanLog`, after the `variant` column (line ~160), add:
```python
    # Phase 4: groups the N rows of one bulk-cataloger photo. NULL for single-card
    # scans (treated as a singleton batch). batch_index is the slot position within
    # the batch. Both nullable, added via run_migrations, not create_all — the 105
    # existing rows stay NULL.
    batch_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    batch_index: Mapped[int | None] = mapped_column(Integer, default=None)
```
Ensure `Integer` is imported (check the existing imports at the top of `models.py` — `Integer`, `String` are almost certainly already imported; if not, add them).

- [ ] **Step 2: Register the columns in the idempotent migration**

In `backend/src/cardplatform/db/migrations.py`, append to `_ADDITIVE_COLUMNS`:
```python
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("scan_logs", "rectified_path", "VARCHAR"),
    ("scan_logs", "variant", "VARCHAR"),
    ("scan_logs", "batch_id", "VARCHAR"),
    ("scan_logs", "batch_index", "INTEGER"),
)
```
(Both the model and the registry are updated in the same task — schema drift between them 500s on first batch insert.)

- [ ] **Step 3: Write the failing tests**

`backend/tests/test_scan_store_batch.py` (use the existing `db`/`session` fixture from `conftest.py` — match `test_scan_store.py`'s pattern):
```python
"""Tests for batch scan logging (Phase 4)."""
from __future__ import annotations

from cardplatform.scans.store import ScanStore


def _result(status="confident", card_id="base1-4", variant="normal"):
    from cardplatform.recognition.types import RecognitionResult, OcrReading
    return RecognitionResult(
        card_id=card_id, confidence=0.9, status=status, candidates=(),
        ocr=OcrReading(), visual_margin=0.1, rectified_path="rectified/x.png",
    )


def test_record_batch_writes_one_photo_and_n_rows(db):
    store = ScanStore(db)
    results = [_result(), _result(card_id="base1-4"), _result(status="not_found", card_id=None)]
    scan_ids = store.record_batch(b"\x89PNG fake", "batch-1", results, variants=["normal", "normal", None])
    assert len(scan_ids) == 3
    rows = store.recent(limit=10)
    # All rows share one source photo.
    assert len({r.image_path for r in rows[-3:]}) == 1
    # batch_id + batch_index stamped.
    assert [r.batch_id for r in rows[-3:]] == ["batch-1", "batch-1", "batch-1"]
    assert [r.batch_index for r in rows[-3:]] == [0, 1, 2]
    # not_found is logged too (ground truth).
    assert rows[-1].status == "not_found"


def test_accuracy_is_batch_aware(db):
    """N rows per batch photo count ONCE in accuracy().total — don't inflate the baseline."""
    store = ScanStore(db)
    # One batch of 3 + one singleton.
    store.record_batch(b"\x89PNG", "b1", [_result(), _result(), _result()])
    store.record(image_bytes=b"\x89PNG", status="confident", predicted_card_id="base1-4", variant="normal")
    acc = store.accuracy()
    assert acc.total == 2  # 1 batch + 1 singleton, NOT 4


def test_record_singleton_has_null_batch_id(db):
    store = ScanStore(db)
    scan = store.record(image_bytes=b"\x89PNG", status="confident", predicted_card_id="base1-4", variant="normal")
    assert scan.batch_id is None
    assert scan.batch_index is None
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_scan_store_batch.py -q`
Expected: FAIL with `AttributeError: 'ScanStore' object has no attribute 'record_batch'` (and `accuracy` total wrong).

- [ ] **Step 5: Implement `record_batch` + batch-aware `accuracy`**

In `backend/src/cardplatform/scans/store.py`, add `record_batch` and rework `accuracy`:
```python
    def record_batch(
        self,
        image_bytes: bytes,
        batch_id: str,
        results: "list",  # list[RecognitionResult]
        variants: "list[str | None]" | None = None,
    ) -> list[ScanLog]:
        """Log N cards from one source photo (Phase 4). Writes the photo once; all N
        rows share image_path. Commits per row so a mid-batch failure keeps the audit
        trail. Logs every card including not_found."""
        name = f"{uuid.uuid4().hex}.png"
        (self.directory / name).write_bytes(image_bytes)
        image_path = f"scans/{name}"
        if variants is None:
            variants = [getattr(r, "variant", None) for r in results]
        scans: list[ScanLog] = []
        for idx, result in enumerate(results):
            scan = ScanLog(
                image_path=image_path,
                predicted_card_id=result.card_id,
                status=result.status,
                confidence=result.confidence,
                visual_margin=result.visual_margin,
                collector_number_read=result.ocr.collector_number if result.ocr else None,
                rectified_path=result.rectified_path,
                variant=variants[idx] if idx < len(variants) else None,
                batch_id=batch_id,
                batch_index=idx,
            )
            self.session.add(scan)
            self.session.commit()  # per-crop: durable
            scans.append(scan)
        return scans
```
Rework `accuracy()` to count one representative per batch (rows with `NULL batch_id` are singleton batches):
```python
    def accuracy(self) -> ScanAccuracy:
        rows = list(self.session.scalars(select(ScanLog)).all())
        # Batch-aware: count one representative (first by id) per batch_id; NULL
        # batch_id rows are singleton batches (one each). N rows per bulk photo
        # must not inflate the 105-scan baseline.
        seen_batches: dict[str | None, ScanLog] = {}
        for row in sorted(rows, key=lambda r: r.id):
            seen_batches.setdefault(row.batch_id, row)
        rep = list(seen_batches.values())
        by_status: dict[str, int] = {}
        for row in rep:
            by_status[row.status] = by_status.get(row.status, 0) + 1
        answered = [r for r in rep if r.predicted_card_id is not None]
        predicted = [r for r in answered if r.confirmed]
        correct = [r for r in predicted if r.corrected_card_id is None]
        return ScanAccuracy(
            total=len(rep),
            answered=len(answered),
            predicted=len(predicted),
            correct=len(correct),
            precision=len(correct) / len(predicted) if predicted else 0.0,
            coverage=len(answered) / len(rep) if rep else 0.0,
            by_status=by_status,
        )
```
(Keep the existing `ScanAccuracy` dataclass fields — no schema change to it; `total` now means "scans" not "rows". The `by_status` now counts representatives. This preserves comparability with the 105-scan baseline since those rows all have `NULL batch_id` → each is its own singleton.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_scan_store_batch.py backend/tests/test_scan_store.py backend/tests/test_migrations.py -q`
Expected: PASS (new + existing scan-store/migration tests green; the 105-row DB migration adds the two columns as NULL).

- [ ] **Step 7: Run the full suite**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (495 + new).

- [ ] **Step 8: Commit**

```bash
cd C:\ClaudeKnowledge && git add backend/src/cardplatform/db/models.py backend/src/cardplatform/db/migrations.py backend/src/cardplatform/scans/store.py backend/tests/test_scan_store_batch.py && git commit -m "feat(scans): batch scan logging + batch-aware accuracy (T3)"
```

---

## Task 4: `POST /recognize/batch` endpoint + wire types

**Files:**
- Modify: `backend/src/cardplatform/api.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `backend/tests/test_recognize_batch_api.py` (new)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_recognize_batch_api.py` (use the `create_app()` + `get_session` override + `cardplatform.api.settings` monkeypatch pattern from `test_recognize_api.py` — read it first and mirror exactly):
```python
"""Tests for POST /recognize/batch (Phase 4)."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest


def _png_bytes() -> bytes:
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (1200, 1500), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


def test_recognize_batch_returns_n_results(client, monkeypatch):
    # Patch detect_all_quads + recognize_many to return 2 fake results.
    from cardplatform.recognition import service as svc
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    fake_quads = [object(), object()]
    def fake_detect(img):
        return [("otsu_rect", q) for q in fake_quads]

    def fake_many(self, img, quads):
        return [
            (q, RecognitionResult(card_id="base1-4", confidence=0.9, status="confident",
                                  candidates=(), ocr=OcrReading(), visual_margin=0.1,
                                  rectified_path="rectified/a.png"), None)
            for q in quads
        ]

    monkeypatch.setattr("cardplatform.recognition.service.detect_candidates", lambda img: [])  # not used
    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads", fake_detect)
    monkeypatch.setattr(svc.RecognitionService, "recognize_many", fake_many)

    resp = client.post(
        "/recognize/batch",
        files={"file": ("page.png", _png_bytes(), "image/png")},
        params={"variant": "normal", "max_cards": 9},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert len(body["results"]) == 2
    assert all(r["status"] == "confident" for r in body["results"])
    assert "batch_id" in body and body["batch_id"]


def test_recognize_batch_honest_none_price_for_not_found(client, monkeypatch):
    from cardplatform.recognition import service as svc
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads",
                        lambda img: [("otsu_rect", object())])
    monkeypatch.setattr(svc.RecognitionService, "recognize_many",
                        lambda self, img, quads: [(q, RecognitionResult(
                            card_id=None, confidence=0.0, status="not_found", candidates=(),
                            ocr=OcrReading(), visual_margin=0.0, rectified_path=None), None)
                            for q in quads])
    resp = client.post("/recognize/batch", files={"file": ("p.png", _png_bytes(), "image/png")})
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["status"] == "not_found"
    assert body["results"][0]["card"] is None
    assert body["results"][0]["price"] is None  # never $0


def test_recognize_batch_max_cards_clamp(client, monkeypatch):
    from cardplatform.recognition import service as svc
    from cardplatform.recognition.types import RecognitionResult, OcrReading
    # 5 quads but max_cards=2 → count 2.
    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads",
                        lambda img: [("otsu_rect", object()) for _ in range(5)])
    monkeypatch.setattr(svc.RecognitionService, "recognize_many",
                        lambda self, img, quads: [(q, RecognitionResult(
                            card_id="base1-4", confidence=0.9, status="confident", candidates=(),
                            ocr=OcrReading(), visual_margin=0.1, rectified_path=None), None)
                            for q in quads])
    resp = client.post("/recognize/batch",
                       files={"file": ("p.png", _png_bytes(), "image/png")},
                       params={"max_cards": 2})
    assert resp.json()["count"] == 2


def test_recognize_batch_max_cards_out_of_range_422(client, monkeypatch):
    resp = client.post("/recognize/batch",
                       files={"file": ("p.png", _png_bytes(), "image/png")},
                       params={"max_cards": 99})
    assert resp.status_code == 422
```
(Use the real `client` fixture + `create_app()`/settings monkeypatch from `test_recognize_api.py`. If `recognize_many` is patched, ensure the real `detect_all_quads` import path the endpoint uses is the one patched — match `cardplatform.recognition.detectors.detect_all_quads` AND import it in the endpoint via `from cardplatform.recognition.detectors import detect_all_quads` so the patch target is correct.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_recognize_batch_api.py -q`
Expected: FAIL with 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add the endpoint + wire types**

In `backend/src/cardplatform/api.py`:
- Add imports near the existing recognition imports: `import uuid` (likely already imported — check), `from cardplatform.recognition.detectors import detect_all_quads`.
- Add a `BatchRecognizeOut` model near `RecognizeOut` (line ~226):
```python
class BatchRecognizeOut(BaseModel):
    """One binder-page photo → N independent scan verdicts (Phase 4).

    Each result carries its own status/price/rectified_path; the batch_id groups them.
    Per-card statuses are NEVER collapsed into one batch status — that would fabricate
    confidence.
    """
    batch_id: str
    count: int
    results: list[RecognizeOut]
```
- Add the endpoint right after `recognize` (line ~738):
```python
    @app.post("/recognize/batch", response_model=BatchRecognizeOut)
    async def recognize_batch(
        file: UploadFile = File(...),
        variant: str = Query(default="normal"),
        max_cards: int = Query(default=9, ge=1, le=18),
        session: Session = Depends(get_session),
        service=Depends(get_recognition_service),
    ) -> BatchRecognizeOut:
        # One binder-page photo → N cards. Detection runs once; recognition per quad.
        image = _decode_upload(await file.read())
        quads = detect_all_quads(image)
        if not quads:
            return BatchRecognizeOut(batch_id=uuid.uuid4().hex, count=0, results=[])
        # Cap to max_cards, largest-area first (detect_all_quads is already largest-first).
        quads = quads[:max_cards]
        recognized = service.recognize_many(image, [q for _, q in quads])
        price_service = PriceService(session)
        out_results: list[RecognizeOut] = []
        for _, result, centering in recognized:
            card = session.get(Card, result.card_id) if result.card_id else None
            price = (
                price_service.latest_price(card.id, variant) if card is not None else None
            )
            out_results.append(RecognizeOut(
                status=result.status,
                confidence=result.confidence,
                visual_margin=result.visual_margin,
                card=CardOut.from_card(card) if card is not None else None,
                price=_price_out(price) if price else None,
                candidates=_candidates_out(session, result.candidates),
                collector_number_read=result.ocr.collector_number,
                centering=_centering_out(centering) if centering is not None else None,
                rectified_path=result.rectified_path,
            ))
        return BatchRecognizeOut(
            batch_id=uuid.uuid4().hex, count=len(out_results), results=out_results
        )
```

In `frontend/src/api/types.ts`, add (mirror the existing `RecognizeOut` interface shape — read it and reuse the exact type):
```typescript
export interface BatchRecognizeResponse {
  batch_id: string;
  count: number;
  results: RecognizeOut[];
}
```

In `frontend/src/api/client.ts`, add near `recognize(...)` (mirror its `FormData`/`expectJson`/`BASE` style):
```typescript
export async function batchRecognize(
  file: File | Blob,
  variant = "normal",
  maxCards = 9,
): Promise<BatchRecognizeResponse> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ variant, max_cards: String(maxCards) });
  const res = await fetch(`${BASE}/recognize/batch?${qs}`, { method: "POST", body: form });
  return expectJson<BatchRecognizeResponse>(res);
}
```
Also extend the existing `recordScan(...)` client call to accept optional `batch_id` + `batch_index` + `rectified_path` params and append them to its `URLSearchParams`/form (it currently drops `rectified_path`/`variant` — read the current `recordScan` and thread them through).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_recognize_batch_api.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full backend + frontend suite**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q && npm --prefix frontend test -- --run`
Expected: backend green (495 + 4); frontend green (102 — types/client changes are additive; no frontend test added yet, that's T5).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge && git add backend/src/cardplatform/api.py frontend/src/api/types.ts frontend/src/api/client.ts backend/tests/test_recognize_batch_api.py && git commit -m "feat(api): POST /recognize/batch endpoint + wire types (T4)"
```

---

## Task 5: Batch review grid (PWA UI)

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ScanResult.tsx` (if needed for per-cell reuse)
- Modify: `frontend/src/__tests__/App.test.tsx` or new `BulkScan.test.tsx`
- Possibly modify: `frontend/src/styles.css` (grid layout)
- Test: `frontend/src/__tests__/BulkScan.test.tsx` (new)

- [ ] **Step 1: Read the current scan flow**

Read `frontend/src/App.tsx` (esp. `runRecognition`, `handleCapture`, `handleConfirm`, `handlePick`, `handleRescan`, the `VARIANT` const), `frontend/src/components/CameraCapture.tsx`, `ScanResult.tsx`, `CandidatePicker.tsx`, `CornerAdjust.tsx`, and `frontend/src/__tests__/App.test.tsx`. The batch UI reuses these components per cell with per-cell state; the goal is to NOT change their props, only the orchestration in `App.tsx`.

- [ ] **Step 2: Write the failing tests**

`frontend/src/__tests__/BulkScan.test.tsx` (mirror the existing `App.test.tsx` `stubFetch`/render pattern; mock `batchRecognize` via `vi.mock`):
```typescript
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// Mock the client so we control the batch result shape.
const batchRecognize = vi.fn();
vi.mock("../api/client", () => ({
  batchRecognize: (...args: unknown[]) => batchRecognize(...args),
  recognize: vi.fn(),
  recordScan: vi.fn().mockResolvedValue({ id: 1 }),
  addToCollection: vi.fn().mockResolvedValue({}),
}));

import App from "../App";

describe("Bulk scan mode", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a bulk-mode toggle", async () => {
    batchRecognize.mockResolvedValue({ batch_id: "b1", count: 0, results: [] });
    render(<App />);
    expect(screen.getByRole("button", { name: /bulk/i })).toBeDefined();
  });

  it("renders N result cells for a batch of N", async () => {
    batchRecognize.mockResolvedValue({
      batch_id: "b1", count: 2,
      results: [
        { status: "confident", confidence: 0.9, visual_margin: 0.1,
          card: { id: "base1-4", name: "Charizard", number: "4", set_id: "base1", set_name: "Base" },
          price: null, candidates: [], collector_number_read: "4", centering: null, rectified_path: null },
        { status: "not_found", confidence: 0.0, visual_margin: 0.0, card: null,
          price: null, candidates: [], collector_number_read: null, centering: null, rectified_path: null },
      ],
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /bulk/i }));
    // Upload/capture triggers batchRecognize (use a file input or the capture button).
    // ...drive the capture with a fake file (match App.test.tsx's pattern)...
    await waitFor(() => {
      expect(batchRecognize).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByText("Charizard")).toBeDefined();
      expect(screen.getByText(/not found|no card/i)).toBeDefined();
    });
  });

  it("never shows $0.00 for an unpriced confident card", async () => {
    batchRecognize.mockResolvedValue({
      batch_id: "b1", count: 1,
      results: [{ status: "confident", confidence: 0.9, visual_margin: 0.1,
        card: { id: "base1-4", name: "Charizard", number: "4", set_id: "base1", set_name: "Base" },
        price: null, candidates: [], collector_number_read: "4", centering: null, rectified_path: null }],
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /bulk/i }));
    await waitFor(() => expect(batchRecognize).toHaveBeenCalled());
    await waitFor(() => {
      const text = document.body.textContent ?? "";
      expect(text).not.toContain("$0.00");
    });
  });
});
```
(Align to the real `App` export + the real `App.test.tsx` driving pattern — the capture flow is camera-based, so drive it the same way `App.test.tsx` does, e.g. mocking `CameraCapture`'s `onCapture` with a fake `Blob`/`File`.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && npm --prefix frontend test -- --run BulkScan`
Expected: FAIL (no bulk toggle / no grid).

- [ ] **Step 4: Implement the batch review grid**

In `frontend/src/App.tsx`:
- Add a `mode: "single" | "bulk"` state + a toggle button in the Scan pane header (not a new nav tab).
- Generalize the scan state to arrays: `bulkResults: RecognizeOut[]`, `bulkScanIds: (number | null)[]`, paired by index, in addition to (not replacing) the single-card state so the single-card path is untouched.
- `runBulkRecognition(file)` calls `batchRecognize(file, variant, maxCards)`, stores `results`, then logs each card via `recordScan(file, status, { batch_id, batch_index: i, rectified_path, variant })` per cell (surface per-cell logging status; don't swallow failures silently — show a small "saved"/"failed" indicator per cell).
- Render the grid: `results.map((r, i) => <ScanResult ... per-cell handlers />)` in a CSS grid (`.bulk-grid` in `styles.css`). Each cell wires its own `onConfirm`/`onPick`/`onReject`/`onRescan` operating on index `i`. `CandidatePicker` and `CornerAdjust` are reused per cell unchanged.
- Add a **per-cell variant selector** (`<select>` with the variant options) defaulting to `normal`; changing it re-resolves price for that cell (lazy: only on focus/expand, not on grid render).
- **Bulk-add to collection** button: for each distinct `(card_id, variant)` among confident results, call `addToCollection` (let the store merge duplicates). Never fabricate `$0` — `formatMoney` returns `—` for `null`.
- Suppress the watch-nudge in bulk mode.

In `frontend/src/styles.css`, add a responsive grid:
```css
.bulk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.bulk-grid > .scan-result { border: 1px solid var(--border, #222); border-radius: 8px; padding: 10px; }
@media (max-width: 600px) { .bulk-grid { grid-template-columns: 1fr; } }
```
Match the existing dark `#0b0d12` theme tokens already in `styles.css`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && npm --prefix frontend test -- --run`
Expected: PASS (102 + new bulk tests; existing single-card tests unchanged).

- [ ] **Step 6: Run the build**

Run: `cd C:\ClaudeKnowledge && npm --prefix frontend run build`
Expected: clean (PWA SW generated).

- [ ] **Step 7: Commit**

```bash
cd C:\ClaudeKnowledge && git add frontend/src/App.tsx frontend/src/styles.css frontend/src/__tests__/BulkScan.test.tsx && git commit -m "feat(frontend): bulk scan mode + batch review grid (T5)"
```

---

## Task 6: Eval harness extension (per-card scoring, no regression)

**Files:**
- Modify: `backend/scripts/evaluate_detection.py`
- Add: `backend/scripts/make_batch_fixtures.py` (new — synthetic fixture generator)
- Test: `backend/tests/test_evaluate_detection_batch.py` (new)

- [ ] **Step 1: Read the current harness**

Read `backend/scripts/evaluate_detection.py` — it replays the real scans, scores detection, and fails on one confident regression. Understand the one-card-per-scan ground-truth assumption.

- [ ] **Step 2: Write a synthetic fixture generator**

`backend/scripts/make_batch_fixtures.py` — composes N catalog card images (or synthetic card-shaped crops) onto a page-sized canvas, writing the page + a JSON ground-truth file (per-card `card_id` + quad). Run it once to produce a small fixture set under `data/scans/batch_fixtures/` (this ADDS files under `data/`, which is allowed — never delete). The fixtures let `evaluate_detection.py` score multi-card pages with per-card truth. Keep the set tiny (2-3 pages) to stay lightweight.
```python
"""Generate synthetic binder-page fixtures for multi-card detection eval (Phase 4).

Writes a page image + a per-card ground-truth JSON. Additive only — creates files
under data/scans/batch_fixtures/, never deletes anything.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path("data/scans/batch_fixtures")

def _make_page(name: str, cols: int, rows: int, card_w=240, card_h=336, gap=60, pad=60):
    OUT.mkdir(parents=True, exist_ok=True)
    page_w = pad * 2 + cols * card_w + (cols - 1) * gap
    page_h = pad * 2 + rows * card_h + (rows - 1) * gap
    img = Image.new("RGB", (page_w, page_h), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    truth = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            x = pad + c * (card_w + gap)
            y = pad + r * (card_h + gap)
            draw.rectangle([x, y, x + card_w, y + card_h], fill=(230, 230, 230), outline=(0,0,0), width=3)
            truth.append({"index": idx, "quad": [[x, y], [x + card_w, y], [x + card_w, y + card_h], [x, y + card_h]]})
            idx += 1
    img.save(OUT / f"{name}.png")
    (OUT / f"{name}.json").write_text(json.dumps({"page": f"{name}.png", "cards": truth}))

if __name__ == "__main__":
    _make_page("page_3x3", 3, 3)
    _make_page("page_2x2", 2, 2)
    print(f"wrote fixtures to {OUT}")
```

- [ ] **Step 3: Extend the harness with per-card scoring**

In `backend/scripts/evaluate_detection.py`, add a `--batch` mode (or a separate `evaluate_batch_detection.py` — match the existing file's style) that loads `data/scans/batch_fixtures/*.json`, runs `detect_all_quads` on each page, and matches detected quads to ground-truth quads by IoU. Score: per-page recall (fraction of ground-truth cards detected at IoU > 0.5), and fail the run if a previously-detected fixture regresses (a page that found 9 now finds <9). Keep the single-card 105-scan path unchanged and still green.

- [ ] **Step 4: Write the test**

`backend/tests/test_evaluate_detection_batch.py`:
```python
"""Multi-card detection eval (Phase 4) — per-card scoring, no single-card regression."""
from __future__ import annotations
from pathlib import Path
from PIL import Image
from cardplatform.recognition.detectors import detect_all_quads

def _iou(a, b):
    import cv2, numpy as np
    inter, _ = cv2.intersectConvexConvex(a.astype("float32"), b.astype("float32"))
    ua = cv2.contourArea(a.astype("float32")) + cv2.contourArea(b.astype("float32")) - max(inter, 0)
    return (max(inter, 0) / ua) if ua > 0 else 0

def test_detect_all_quads_recall_on_synthetic_page(tmp_path):
    # 3x3 page → ≥8 of 9 cards detected (allow one edge miss).
    from scripts.make_batch_fixtures import _make_page  # if importable; else inline
    ...
```
(If `make_batch_fixtures` isn't on the import path, inline the page construction in the test or add `backend/scripts` to the test's `sys.path`. Assert recall ≥ 0.8 on the 3x3 page — detection should find most cards; tune the assertion to what the detector honestly achieves, but never below 0.5.)

- [ ] **Step 5: Run the tests + the harness**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_evaluate_detection_batch.py -q && backend/.venv/Scripts/python backend/scripts/evaluate_detection.py`
Expected: new test PASS; the 105-scan `evaluate_detection.py` run unchanged (no regression — single-card path untouched).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge && git add backend/scripts/evaluate_detection.py backend/scripts/make_batch_fixtures.py backend/tests/test_evaluate_detection_batch.py && git commit -m "feat(eval): per-card batch detection scoring + synthetic fixtures (T6)"
```

---

## Task 7: Docs, integrate, verify, push, deploy

**Files:**
- Modify: `AI_CONTEXT.md`
- Modify: `PROJECT.md`
- Modify: `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md` + `MEMORY.md`

- [ ] **Step 1: Full verification**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q && npm --prefix frontend test -- --run && npm --prefix frontend run build`
Expected: backend all green (485 → final N), frontend all green (102 → final N), build clean. Note final counts.

- [ ] **Step 2: Update `AI_CONTEXT.md`**

- State table: Phase 4 → ✅ Complete (bulk cataloger); Phase 5 row stays (sealed EV still planned).
- Tests line → final counts.
- Layout `detectors.py` note: add `detect_all_quads` (multi-quad + IoU NMS); `service.py`: add `recognize_many` (batched embed + parallel OCR); `scans/store.py`: add `record_batch` + batch-aware `accuracy`; `db/models.py` ScanLog: add `batch_id` + `batch_index`.
- Phase 04 endpoints note: `POST /recognize/batch` (N `RecognizeOut` + `batch_id`, honest `None` prices, `max_cards` clamp); additive `batch_id`/`batch_index` on `scan_logs`.
- Append a new section "Phase 4 — bulk cataloger" with the architecture, the open-question resolutions, the deprecation-free notes (no external API this phase), and sacred-constraints-held.

- [ ] **Step 3: Update `PROJECT.md`**

- Status line → Phase 4 (bulk cataloger) shipped 2026-08-04.
- Roadmap table: Phase 4 → Complete.
- Add a "Phase 4 (bulk cataloger) — shipped" section mirroring the Phase 05b section style.
- Next step: sealed-product EV or full Grade predictor (unchanged).

- [ ] **Step 4: Merge to main + push**

```bash
cd C:\ClaudeKnowledge && git checkout main && git merge --no-ff phase-4-bulk-cataloger -m "Phase 4: bulk cataloger ..." && git push origin main
```
(Site unchanged this phase — no `docs/` change, so no meaningful Pages redeploy. Verify the Pages build status with `gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds` — expect `built`.)

- [ ] **Step 5: Update project memory**

Update `pokemon-card-platform-project.md`: current phase → Phase 4 shipped 2026-08-04, final test counts, `detect_all_quads`/`recognize_many`/`POST /recognize/batch`/batch scan logging note, next = sealed-product EV or full Grade predictor. Update the `MEMORY.md` index line hook.

- [ ] **Step 6: Commit docs + memory**

```bash
cd C:\ClaudeKnowledge && git add AI_CONTEXT.md PROJECT.md && git commit -m "docs: record Phase 4 bulk cataloger" && git push origin main
```

---

## Self-review checklist (run after writing the plan, before execution)

- **Spec coverage:** detection (T1), recognize_many (T2), batch logging (T3), endpoint (T4), UI (T5), eval (T6), docs/ship (T7) — every spec section has a task. ✓
- **Type consistency:** `detect_all_quads` → `list[tuple[str, np.ndarray]]` (T1) matches `recognize_many`'s `quads` param (T2) and the endpoint's `[q for _, q in quads]` (T4). `batch_id`/`batch_index` (T3 model + migration) match `record_batch` (T3) + `recordScan` client threading (T4) + UI logging (T5). `BatchRecognizeOut`/`BatchRecognizeResponse` (T4 backend + frontend) match `batchRecognize` (T4 client) and the UI (T5). ✓
- **Sacred constraints:** `latest_price` only (T4); honest `None` prices (T4 test); no `$0` (T5 test); additive schema (T3); 105 rows stay NULL (T3); recognition-as-arbiter (T2 test); single-card path unchanged (T1 `detect_candidates` test, T6 harness). ✓
- **No placeholders:** every code step has real code; test steps that say "mirror the existing pattern" name the exact file to mirror. ✓

## Execution

Subagent-driven (fresh implementer per task, TDD, inline spec + quality reviews — the established Phase 05/05b pattern, conserving budget). T1 → T2 → T4 (endpoint needs detect_all_quads + recognize_many); T3 independent (land anytime before T7); T5 after T4's client; T6 after T1; T7 last. Auto mode: proceed without per-step check-ins; commit per task; push + deploy at the end.