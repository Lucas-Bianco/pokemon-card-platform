# Phase 1a — Recognition Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a photograph of a Pokémon card into a confidently identified, priced card — server-side, end to end, with calibrated uncertainty.

**Architecture:** Rectify the card to a canonical rectangle, then run two independent recognition engines on it — a CLIP visual-embedding search over a FAISS index of all 20,444 catalog cards, and targeted OCR of the collector number — and fuse them into a single calibrated confidence. Agreement auto-confirms; disagreement returns ranked candidates for the user to choose.

**Tech Stack:** open-clip-torch (ViT-B-32, laion2b), FAISS (exact inner-product), rapidocr-onnxruntime, OpenCV, on the existing Python 3.12 / FastAPI / SQLAlchemy Phase 0 foundation.

---

## Scope

This plan is **Phase 1a: the recognition engine only** — everything server-side, ending at a working
`POST /recognize` endpoint. **Phase 1b (the camera PWA: live overlay, client-side rectification,
top-3 picker UI) gets its own plan.**

That split is deliberate and mirrors Phase 0's. 1a ships something independently usable and testable
— you can POST a card photo and get back an identified, priced card — without any frontend existing.
It also front-loads all the technical risk.

### Deliberately deferred: variant disambiguation (spec §2.5)

The design spec calls for specular/glare analysis to separate holo from reverse-holo from non-holo.
**This plan does not implement it**, and that is a conscious deferral rather than an oversight.

The reason is evidential: holo foiling is a property of the *physical card under real light*.
Catalog reference images are flat scans that show no foil behaviour at all, so there is nothing here
to develop or test against — any specular heuristic written now would be fitted to imaginary data.

Until then, `POST /recognize` takes `variant` as an explicit parameter and defaults to `"normal"`,
so the caller decides. **Phase 1b's first task collects real phone photos**, which is the point at
which variant disambiguation becomes developable. It is recorded there, not dropped.

## Prerequisites from Phase 0

Complete and merged. This plan builds on:

- `Card` table: **20,444 rows**, every one with a non-null `image_small` (verified: 0 missing,
  0 duplicates, 0 orphan `set_id`s)
- `Database`, `Settings`, `PriceService.latest_price(card_id, variant)`, `CollectionStore.add(...)`
- `api.py` with a `create_app()` factory and a `get_session` dependency
- `cli.py` with an argparse subcommand structure

---

## Empirical findings this plan is built on

**Measured on this machine (RTX 5070 Ti) on 2026-07-29.** These are not assumptions — do not
re-derive them, but do re-verify the accuracy numbers at full scale in Task 11.

### The encoder works, and it is fast

`open_clip` ViT-B-32 / `laion2b_s34b_b79k`, on GPU:

| Metric | Value |
|---|---|
| Embedding speed | **2.2 ms/card** |
| Full-catalog embed time | **~0.7 min** for 20,444 cards |
| Vector dimension | 512 |
| Full index size | **~42 MB** |
| FAISS exact search | **0.01 ms/query** — no approximate index needed at this scale |

### Accuracy degrades with index size — this is the finding that shapes the design

Same 400 degraded query images (blur + dim + 3° rotation + JPEG q45), against a growing index:

| Index size | top-1 | top-3 | mean margin |
|---|---|---|---|
| 300 | 100.0% | 100.0% | 0.112 |
| 1,000 | 96.8% | 100.0% | 0.091 |
| 2,000 | 96.0% | 98.2% | 0.083 |
| 2,993 | **93.8%** | 97.5% | 0.076 |

Extrapolating, visual-only top-1 at the full 20,444 lands near **85%**. **Visual matching alone is
not sufficient.**

### But the failures are exactly what OCR fixes

The actual top-1 misses at 2,993:

```
me2pt5-114  Stunfisk ex        -> me2pt5-252  Stunfisk ex        margin=0.006
ex15-82     TV Reporter        -> ex3-88      TV Reporter        margin=0.009
me3-71      Crushing Hammer    -> sm8-192     Wait and See Hammer margin=0.019
```

Same name, different print or different set. A collector number disambiguates every one of these
instantly. **This is the empirical justification for the hybrid design** — the two engines fail on
genuinely different inputs.

### Margin is a usable confidence signal

At the full 2,993-card index:

| | count | mean top-similarity | mean margin |
|---|---|---|---|
| Correct | 375 | 0.782 | **0.081** |
| Incorrect | 25 | 0.719 | **0.012** |

A **6.8× separation** in margin. This is what Task 9's fusion uses, and Task 11 calibrates the
threshold against real data rather than guessing a constant.

### OCR reads the collector number reliably

`rapidocr-onnxruntime` on a real Charizard (`base1-4`, 600×825):

```
'4/102*'     conf=0.90   y=0.95-0.97  x=0.86
'Charizard'  conf=0.99   y=0.06-0.11  x=0.26
```

The collector number sits in a **predictable bottom-right region** on a rectified card. Full-card
OCR took **1.31 s** — too slow for interactive use, which is why Task 8 crops to the number region
first rather than OCR-ing the whole card.

### Two install traps that will cost an evening each

Both hit during research on this exact machine:

1. **`pip install open-clip-torch` silently downgraded torch to CPU-only** (`2.13.0+cpu`,
   `cuda: False`), destroying the CUDA build. It pulls torch from PyPI, not the CUDA index.
2. **Repairing with `--force-reinstall torch` alone then broke torchvision** —
   `RuntimeError: operator torchvision::nms does not exist`, because torchvision was still built
   against the old wheel.

**torch and torchvision must be installed together, from the CUDA index, after any package that
depends on them.** Task 1 encodes this.

### An image-pipeline detail that breaks naive code

- Card images span **two CDNs**: 19,783 on `images.pokemontcg.io`, 661 on `images.scrydex.com`.
- **661 URLs have no file extension** — they end in `/small`, not `.png`. Any cache-filename logic
  doing `url.rsplit(".", 1)[-1]` corrupts 3% of the catalog. Task 3 derives filenames from
  `card_id` instead.

---

## File structure

```
backend/src/cardplatform/recognition/
  __init__.py
  types.py        # Candidate, OcrReading, RecognitionResult — shared vocabulary
  images.py       # ReferenceImageCache: download + local storage of catalog images
  rectify.py      # detect card quad, perspective-warp to canonical 600x825
  encoder.py      # CardEncoder: PIL image -> normalized 512-d vector
  index.py        # CardIndex: FAISS build / save / load / search
  ocr.py          # CollectorNumberReader: targeted region OCR
  fusion.py       # fuse visual candidates + OCR -> RecognitionResult
  service.py      # RecognitionService: orchestrates the full pipeline
backend/tests/
  test_recognition_types.py
  test_images.py
  test_rectify.py
  test_encoder.py
  test_index.py
  test_ocr.py
  test_fusion.py
  test_recognition_service.py
  test_recognize_api.py
backend/scripts/
  evaluate_recognition.py   # accuracy + threshold calibration harness
```

Each module has one responsibility and a narrow interface. `fusion.py` is deliberately pure —
it takes data and returns a decision, with no I/O — so the arbitration logic can be tested
exhaustively without models or a database.

---

## Task 1: ML dependencies with the verified install order

No TDD — this is environment setup. **Do not reorder these steps**; the order is the fix for the two traps above.

**Files:** Modify `backend/pyproject.toml`

- [ ] **Step 1: Add the recognition dependencies**

In `backend/pyproject.toml`, add a new optional-dependency group. Do not put these in the base
`dependencies` — Phase 0's CLI and API must stay installable without a 3 GB ML stack.

```toml
[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-cov>=5.0", "respx>=0.21"]
ml = [
    "open-clip-torch>=2.24",
    "faiss-cpu>=1.8",
    "opencv-python>=4.9",
    "pillow>=10.0",
    "numpy>=2.0",
    "rapidocr-onnxruntime>=1.3",
]
```

- [ ] **Step 2: Install the ML group**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\backend[dev,ml]"
```

- [ ] **Step 3: Repair torch and torchvision together**

This step is mandatory even if CUDA worked before — Step 2 will have clobbered it.

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

- [ ] **Step 4: Verify the whole stack in one shot**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -c "import torch, torchvision, open_clip, faiss, cv2; from rapidocr_onnxruntime import RapidOCR; print('torch', torch.__version__); print('torchvision', torchvision.__version__); print('cuda', torch.cuda.is_available()); print('device', torch.cuda.get_device_name(0)); print('capability', torch.cuda.get_device_capability(0)); print('faiss', faiss.__version__); print('cv2', cv2.__version__); print('ocr OK')"
```

Expected — all five lines must be right:
```
torch 2.11.0+cu128
torchvision 0.26.0+cu128
cuda True
device NVIDIA GeForce RTX 5070 Ti
capability (12, 0)
faiss 1.14.3
cv2 5.0.0
ocr OK
```

If `cuda` is `False`, or either version string lacks `+cu128`, repeat Step 3. Do not continue —
every later task will be 20× slower and Task 11 will take hours.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml && git commit -m "build: add ml dependency group for recognition"
```

---

## Task 2: Recognition settings and shared types

**Files:**
- Create: `backend/src/cardplatform/recognition/__init__.py` (empty)
- Create: `backend/src/cardplatform/recognition/types.py`
- Modify: `backend/src/cardplatform/config.py`
- Test: `backend/tests/test_recognition_types.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_recognition_types.py`:

```python
import pytest

from cardplatform.config import Settings
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult


def test_settings_expose_recognition_paths(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.reference_image_dir == tmp_path / "reference_images"
    assert s.index_path == tmp_path / "card_index.faiss"
    assert s.index_ids_path == tmp_path / "card_index_ids.json"


def test_settings_expose_encoder_defaults(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.encoder_model == "ViT-B-32"
    assert s.encoder_pretrained == "laion2b_s34b_b79k"
    assert s.rectified_size == (600, 825)


def test_candidate_is_frozen():
    c = Candidate(card_id="base1-4", visual_score=0.91)
    with pytest.raises(Exception):
        c.card_id = "other"


def test_ocr_reading_defaults_are_empty():
    r = OcrReading()
    assert r.collector_number is None
    assert r.printed_total is None
    assert r.raw_regions == ()


def test_recognition_result_reports_status():
    result = RecognitionResult(
        card_id="base1-4",
        confidence=0.95,
        status="confident",
        candidates=(Candidate("base1-4", 0.91),),
        ocr=OcrReading(collector_number="4", printed_total="102"),
        visual_margin=0.14,
    )
    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.candidates[0].card_id == "base1-4"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_types.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition'`

- [ ] **Step 3: Write the types**

`backend/src/cardplatform/recognition/__init__.py`: create as an empty file.

`backend/src/cardplatform/recognition/types.py`:

```python
"""Shared vocabulary for the recognition pipeline.

These are the only types that cross module boundaries, so the visual matcher, the OCR
reader, and the fusion layer can each be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["confident", "ambiguous", "not_found"]


@dataclass(frozen=True)
class Candidate:
    """One possible card identity, scored by visual similarity."""

    card_id: str
    visual_score: float


@dataclass(frozen=True)
class OcrReading:
    """What OCR could read off the rectified card.

    Every field is optional: glare, blur, and angle routinely defeat OCR, and the
    fusion layer is expected to cope with a completely empty reading.
    """

    collector_number: str | None = None
    printed_total: str | None = None
    name_text: str | None = None
    raw_regions: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class RecognitionResult:
    """The pipeline's decision, always with calibrated uncertainty attached.

    `status` is the field callers should branch on:
      confident  -> card_id is trustworthy, auto-confirm
      ambiguous  -> show `candidates` and let the user pick
      not_found  -> nothing plausible; card_id is None
    """

    card_id: str | None
    confidence: float
    status: Status
    candidates: tuple[Candidate, ...]
    ocr: OcrReading
    visual_margin: float
```

- [ ] **Step 4: Add the settings**

In `backend/src/cardplatform/config.py`, add these fields to the `Settings` class, after the
existing HTTP fields:

```python
    # --- recognition (Phase 1a) ---
    # ViT-B-32/laion2b measured at 2.2 ms/card on an RTX 5070 Ti: ~0.7 min for the
    # full 20,444-card catalog, 512-d vectors, ~42 MB index.
    encoder_model: str = Field(default="ViT-B-32")
    encoder_pretrained: str = Field(default="laion2b_s34b_b79k")
    rectified_size: tuple[int, int] = Field(default=(600, 825))
    visual_top_k: int = Field(default=5)
```

And add these properties alongside the existing ones:

```python
    @property
    def reference_image_dir(self) -> Path:
        return self.data_dir / "reference_images"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "card_index.faiss"

    @property
    def index_ids_path(self) -> Path:
        return self.data_dir / "card_index_ids.json"
```

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_types.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/recognition backend/src/cardplatform/config.py backend/tests/test_recognition_types.py && git commit -m "feat: add recognition types and settings"
```

---

## Task 3: Reference image cache

**Files:**
- Create: `backend/src/cardplatform/recognition/images.py`
- Test: `backend/tests/test_images.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_images.py`:

```python
import httpx
import respx
from PIL import Image

from cardplatform.config import Settings
from cardplatform.recognition.images import ReferenceImageCache


def _png_bytes(color=(200, 30, 30)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (60, 82), color).save(buf, "PNG")
    return buf.getvalue()


def test_path_for_uses_card_id_not_url_extension(tmp_path):
    """661 catalog URLs end in '/small' with no extension. Deriving the filename
    from the URL would corrupt 3% of the cache."""
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    path = cache.path_for("sv8pt5-160")

    assert path.name == "sv8pt5-160.png"
    assert path.parent == tmp_path / "reference_images"


@respx.mock
def test_fetch_downloads_and_stores(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/base1/4.png"
    respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    path = cache.fetch("base1-4", url)

    assert path.exists()
    assert Image.open(path).size == (60, 82)


@respx.mock
def test_fetch_is_skipped_when_already_cached(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.scrydex.com/whatever/small"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    cache.fetch("sv8pt5-160", url)
    cache.fetch("sv8pt5-160", url)

    assert route.call_count == 1


@respx.mock
def test_extensionless_url_still_cached(tmp_path):
    """Guards the two-CDN / no-extension case explicitly."""
    settings = Settings(data_dir=tmp_path)
    url = "https://images.scrydex.com/abc/small"
    respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    path = cache.fetch("me2pt5-234", url)

    assert path.name == "me2pt5-234.png"
    assert Image.open(path).size == (60, 82)


@respx.mock
def test_failed_download_returns_none_and_writes_nothing(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/nope/1.png"
    respx.get(url).mock(return_value=httpx.Response(404))
    cache = ReferenceImageCache(settings)

    assert cache.fetch("nope-1", url) is None
    assert not cache.path_for("nope-1").exists()


@respx.mock
def test_partial_write_is_not_left_behind_on_corrupt_response(tmp_path):
    """A truncated body must not leave an unopenable file that later looks cached."""
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/bad/1.png"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"not-an-image"))
    cache = ReferenceImageCache(settings)

    assert cache.fetch("bad-1", url) is None
    assert not cache.path_for("bad-1").exists()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_images.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.images'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/images.py`:

```python
"""Local cache of catalog card images, used to build the reference embedding index.

Filenames are derived from `card_id`, never from the URL: 661 of the 20,444 catalog
images are served from images.scrydex.com with no file extension (they end in '/small'),
so URL-based naming would corrupt 3% of the cache.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from cardplatform.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class ReferenceImageCache:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.directory = self.settings.reference_image_dir
        self.directory.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=self.settings.http_timeout_seconds, follow_redirects=True
        )

    def path_for(self, card_id: str) -> Path:
        return self.directory / f"{card_id}.png"

    def is_cached(self, card_id: str) -> bool:
        return self.path_for(card_id).exists()

    def fetch(self, card_id: str, url: str) -> Path | None:
        """Download and cache one image. Returns None on any failure — a missing
        reference image must degrade the index, not abort the whole build."""
        target = self.path_for(card_id)
        if target.exists():
            return target

        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("reference image fetch failed for %s: %s", card_id, exc)
            return None

        try:
            # Decode before writing: a truncated or non-image body must not leave a
            # file behind that later looks cached.
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001 - PIL raises a wide variety here
            logger.warning("reference image unreadable for %s: %s", card_id, exc)
            return None

        image.save(target, "PNG")
        return target

    def load(self, card_id: str) -> Image.Image | None:
        path = self.path_for(card_id)
        if not path.exists():
            return None
        return Image.open(path).convert("RGB")
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_images.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/images.py backend/tests/test_images.py && git commit -m "feat: add reference image cache keyed by card id"
```

---

## Task 4: Card rectification

**Files:**
- Create: `backend/src/cardplatform/recognition/rectify.py`
- Test: `backend/tests/test_rectify.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_rectify.py`:

```python
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
    # inner detail so the crop is visually distinguishable
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_rectify.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.rectify'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/rectify.py`:

```python
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
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_rectify.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/rectify.py backend/tests/test_rectify.py && git commit -m "feat: add card detection and perspective rectification"
```

---

## Task 5: Card encoder

**Files:**
- Create: `backend/src/cardplatform/recognition/encoder.py`
- Test: `backend/tests/test_encoder.py`

The encoder is slow to construct (it loads model weights), so it is lazily initialized and the
test module shares one instance.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_encoder.py`:

```python
import numpy as np
import pytest
from PIL import Image

from cardplatform.config import Settings
from cardplatform.recognition.encoder import CardEncoder


@pytest.fixture(scope="module")
def encoder():
    return CardEncoder(Settings())


def _solid(color) -> Image.Image:
    return Image.new("RGB", (600, 825), color)


def test_embed_returns_unit_vector(encoder):
    vector = encoder.embed(_solid((200, 40, 40)))

    assert vector.shape == (encoder.dimension,)
    assert vector.dtype == np.float32
    assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)


def test_dimension_is_512_for_vit_b_32(encoder):
    assert encoder.dimension == 512


def test_embed_many_matches_embed_one(encoder):
    images = [_solid((200, 40, 40)), _solid((40, 200, 40))]

    batch = encoder.embed_many(images)

    assert batch.shape == (2, encoder.dimension)
    assert np.allclose(batch[0], encoder.embed(images[0]), atol=1e-4)


def test_identical_images_are_more_similar_than_different_ones(encoder):
    red_a = encoder.embed(_solid((200, 40, 40)))
    red_b = encoder.embed(_solid((200, 40, 40)))
    green = encoder.embed(_solid((40, 200, 40)))

    assert float(red_a @ red_b) > float(red_a @ green)


def test_embed_many_of_empty_list_returns_empty_array(encoder):
    result = encoder.embed_many([])

    assert result.shape == (0, encoder.dimension)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_encoder.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.encoder'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/encoder.py`:

```python
"""Wraps the CLIP image encoder.

Measured on an RTX 5070 Ti: 2.2 ms/card, 512-d vectors, so the full 20,444-card catalog
embeds in about 40 seconds. Vectors are L2-normalized on the way out, which lets FAISS
inner-product search act as cosine similarity.
"""

from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image

from cardplatform.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class CardEncoder:
    def __init__(self, settings: Settings | None = None) -> None:
        import open_clip

        self.settings = settings or default_settings
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            logger.warning(
                "CUDA unavailable — encoding will be roughly 20x slower. "
                "Check that torch was installed from the cu128 index."
            )

        model, _, preprocess = open_clip.create_model_and_transforms(
            self.settings.encoder_model, pretrained=self.settings.encoder_pretrained
        )
        self._model = model.to(self.device).eval()
        self._preprocess = preprocess
        self.dimension = int(self._model.visual.output_dim)

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image], batch_size: int = 128) -> np.ndarray:
        if not images:
            return np.empty((0, self.dimension), dtype=np.float32)

        chunks: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(images), batch_size):
                batch = images[start : start + batch_size]
                tensor = torch.stack([self._preprocess(im) for im in batch]).to(self.device)
                vectors = self._model.encode_image(tensor)
                vectors = vectors / vectors.norm(dim=-1, keepdim=True)
                chunks.append(vectors.cpu().numpy().astype(np.float32))
        return np.vstack(chunks)
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_encoder.py -v
```

Expected: 5 passed. First run downloads model weights (~600 MB) and takes a couple of minutes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/encoder.py backend/tests/test_encoder.py && git commit -m "feat: add clip card encoder"
```

---

## Task 6: FAISS index

**Files:**
- Create: `backend/src/cardplatform/recognition/index.py`
- Test: `backend/tests/test_index.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_index.py`:

```python
import numpy as np
import pytest

from cardplatform.config import Settings
from cardplatform.recognition.index import CardIndex


def _unit(values) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def vectors():
    return np.vstack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])])


def test_build_and_search_returns_nearest_first(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    results = index.search(_unit([0.9, 0.1, 0]), top_k=2)

    assert [c.card_id for c in results] == ["a", "b"]
    assert results[0].visual_score > results[1].visual_score


def test_search_scores_are_cosine_similarity(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    results = index.search(_unit([1, 0, 0]), top_k=1)

    assert results[0].visual_score == pytest.approx(1.0, abs=1e-5)


def test_save_and_load_roundtrip(tmp_path, vectors):
    settings = Settings(data_dir=tmp_path)
    CardIndex(settings).build(["a", "b", "c"], vectors).save()

    reloaded = CardIndex(settings)
    reloaded.load()

    assert reloaded.size == 3
    assert [c.card_id for c in reloaded.search(_unit([0, 1, 0]), top_k=1)] == ["b"]


def test_load_without_saved_index_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="no index"):
        CardIndex(Settings(data_dir=tmp_path)).load()


def test_search_before_build_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not loaded"):
        CardIndex(Settings(data_dir=tmp_path)).search(_unit([1, 0, 0]), top_k=1)


def test_build_rejects_mismatched_lengths(tmp_path, vectors):
    with pytest.raises(ValueError, match="length"):
        CardIndex(Settings(data_dir=tmp_path)).build(["a", "b"], vectors)


def test_top_k_larger_than_index_is_clamped(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    assert len(index.search(_unit([1, 0, 0]), top_k=50)) == 3
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_index.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.index'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/index.py`:

```python
"""FAISS index over reference card embeddings.

At 20,444 vectors an exact inner-product index searches in ~0.01 ms, so there is no
reason to accept the accuracy loss of an approximate index. Vectors arrive normalized
from CardEncoder, which makes inner product equal to cosine similarity.
"""

from __future__ import annotations

import json

import faiss
import numpy as np

from cardplatform.config import Settings, settings as default_settings
from cardplatform.recognition.types import Candidate


class CardIndex:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self._index: faiss.Index | None = None
        self._card_ids: list[str] = []

    @property
    def size(self) -> int:
        return 0 if self._index is None else self._index.ntotal

    def build(self, card_ids: list[str], vectors: np.ndarray) -> "CardIndex":
        if len(card_ids) != len(vectors):
            raise ValueError(
                f"card_ids and vectors length mismatch: {len(card_ids)} vs {len(vectors)}"
            )
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        self._index = index
        self._card_ids = list(card_ids)
        return self

    def save(self) -> None:
        if self._index is None:
            raise RuntimeError("index not loaded; build it before saving")
        self.settings.ensure_dirs()
        faiss.write_index(self._index, str(self.settings.index_path))
        self.settings.index_ids_path.write_text(
            json.dumps(self._card_ids), encoding="utf-8"
        )

    def load(self) -> "CardIndex":
        if not self.settings.index_path.exists() or not self.settings.index_ids_path.exists():
            raise FileNotFoundError(
                f"no index at {self.settings.index_path}; run 'cardplatform build-index' first"
            )
        self._index = faiss.read_index(str(self.settings.index_path))
        self._card_ids = json.loads(
            self.settings.index_ids_path.read_text(encoding="utf-8")
        )
        return self

    def search(self, vector: np.ndarray, top_k: int) -> list[Candidate]:
        if self._index is None:
            raise RuntimeError("index not loaded; call build() or load() first")
        query = np.ascontiguousarray(vector.reshape(1, -1), dtype=np.float32)
        scores, positions = self._index.search(query, min(top_k, self._index.ntotal))
        return [
            Candidate(card_id=self._card_ids[position], visual_score=float(score))
            for score, position in zip(scores[0], positions[0])
            if position != -1
        ]
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_index.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/index.py backend/tests/test_index.py && git commit -m "feat: add faiss card index with exact search"
```

---

## Task 7: Collector number OCR

**Files:**
- Create: `backend/src/cardplatform/recognition/ocr.py`
- Test: `backend/tests/test_ocr.py`

Measured on a real card: the collector number `4/102` sits at y≈0.95–0.97, x≈0.86 of a rectified
image, and full-card OCR costs 1.31 s. Cropping to the bottom strip first is what makes this fast
enough to be interactive.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_ocr.py`:

```python
import pytest

from cardplatform.recognition.ocr import (
    CollectorNumberReader,
    normalize_collector_number,
    parse_number_text,
)


def test_parse_number_text_splits_number_and_total():
    assert parse_number_text("4/102") == ("4", "102")


def test_parse_number_text_tolerates_trailing_symbols():
    """Real OCR of base1-4 returned '4/102*' — the rarity glyph bleeds in."""
    assert parse_number_text("4/102*") == ("4", "102")


def test_parse_number_text_handles_promo_style_numbers():
    assert parse_number_text("SV049/SV122") == ("SV049", "SV122")


def test_parse_number_text_rejects_non_numbers():
    assert parse_number_text("Charizard") == (None, None)
    assert parse_number_text("") == (None, None)


def test_parse_number_text_handles_missing_total():
    assert parse_number_text("179") == ("179", None)


def test_normalize_strips_leading_zeros_for_matching():
    assert normalize_collector_number("004") == "4"
    assert normalize_collector_number("SV049") == "SV49"
    assert normalize_collector_number(None) is None


def test_normalize_is_idempotent():
    assert normalize_collector_number(normalize_collector_number("004")) == "4"


@pytest.mark.parametrize("junk", ["", "   ", "|||"])
def test_parse_handles_ocr_junk(junk):
    assert parse_number_text(junk) == (None, None)


def test_reader_returns_empty_reading_for_blank_image():
    from PIL import Image

    reading = CollectorNumberReader().read(Image.new("RGB", (600, 825), (255, 255, 255)))

    assert reading.collector_number is None
    assert reading.raw_regions == ()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_ocr.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.ocr'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/ocr.py`:

```python
"""Reads the collector number off a rectified card.

The collector number plus set is a unique key for a Pokemon card, which makes it an
extremely strong independent signal — and one that fails on completely different inputs
than visual embedding does.

Measured on a real rectified card (base1-4, 600x825): the number '4/102*' was read at
y 0.95-0.97, x 0.86 with confidence 0.90, while whole-card OCR cost 1.31 s. Cropping to
the bottom strip first is what keeps this interactive.
"""

from __future__ import annotations

import logging
import re

import numpy as np
from PIL import Image

from cardplatform.recognition.types import OcrReading

logger = logging.getLogger(__name__)

# Bottom strip of a rectified card, where the collector number is printed.
_NUMBER_REGION = (0.55, 0.90, 1.0, 1.0)  # left, top, right, bottom as fractions

_NUMBER_PATTERN = re.compile(r"([A-Z]{0,3}\d{1,4})\s*/\s*([A-Z]{0,3}\d{1,4})")
_BARE_NUMBER_PATTERN = re.compile(r"^([A-Z]{0,3}\d{1,4})$")


def parse_number_text(text: str) -> tuple[str | None, str | None]:
    """Extract (collector_number, printed_total) from an OCR fragment."""
    if not text:
        return (None, None)
    cleaned = text.strip().upper().replace(" ", "")

    match = _NUMBER_PATTERN.search(cleaned)
    if match:
        return (match.group(1), match.group(2))

    bare = _BARE_NUMBER_PATTERN.match(cleaned)
    if bare:
        return (bare.group(1), None)
    return (None, None)


def normalize_collector_number(number: str | None) -> str | None:
    """Canonical form for comparison against the catalog.

    The catalog stores '4' where a card prints '004', and 'SV49' where OCR may read
    'SV049', so leading zeros are stripped from the numeric part only.
    """
    if number is None:
        return None
    cleaned = number.strip().upper()
    match = re.match(r"^([A-Z]*)(\d+)$", cleaned)
    if not match:
        return cleaned
    prefix, digits = match.groups()
    return f"{prefix}{int(digits)}"


class CollectorNumberReader:
    def __init__(self) -> None:
        self._engine = None  # loaded lazily; construction is expensive

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read(self, rectified: Image.Image) -> OcrReading:
        """OCR the number region of a rectified card. Never raises."""
        width, height = rectified.size
        left, top, right, bottom = _NUMBER_REGION
        crop = rectified.crop(
            (int(width * left), int(height * top), int(width * right), int(height * bottom))
        )
        # Upscale: the number is small, and OCR accuracy improves markedly with size.
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)

        try:
            results, _ = self._get_engine()(np.array(crop))
        except Exception as exc:  # noqa: BLE001 - OCR engines raise broadly
            logger.warning("ocr failed: %s", exc)
            return OcrReading()

        if not results:
            return OcrReading()

        regions = tuple(str(text) for _, text, _ in results)
        for text in regions:
            number, total = parse_number_text(text)
            if number is not None:
                return OcrReading(
                    collector_number=number, printed_total=total, raw_regions=regions
                )
        return OcrReading(raw_regions=regions)
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_ocr.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Verify against a real card image**

This proves the region crop actually contains the number on real data, not just fixtures.

Create `backend/scripts/check_ocr_region.py`:

```python
"""Confirms the number region crop captures the collector number on real cards."""

import io

import httpx
from PIL import Image

from cardplatform.recognition.ocr import CollectorNumberReader

CARDS = {
    "base1-4": ("https://images.pokemontcg.io/base1/4_hires.png", "4"),
    "hgss4-1": ("https://images.pokemontcg.io/hgss4/1_hires.png", "1"),
}

reader = CollectorNumberReader()
for card_id, (url, expected) in CARDS.items():
    raw = httpx.get(url, timeout=30, follow_redirects=True).content
    image = Image.open(io.BytesIO(raw)).convert("RGB").resize((600, 825))
    reading = reader.read(image)
    status = "OK " if reading.collector_number == expected else "MISS"
    print(f"{status} {card_id}: read={reading.collector_number!r} "
          f"total={reading.printed_total!r} expected={expected!r}")
    print(f"     regions: {reading.raw_regions}")
```

Run it:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe backend/scripts/check_ocr_region.py
```

Expected: `OK` for both cards. If either misses, widen `_NUMBER_REGION` and re-run — report what
you changed and why. Do not proceed with a region that cannot read a clean reference image.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/recognition/ocr.py backend/tests/test_ocr.py backend/scripts/check_ocr_region.py && git commit -m "feat: add targeted collector number ocr"
```

---

## Task 8: Fusion and calibrated confidence

**Files:**
- Create: `backend/src/cardplatform/recognition/fusion.py`
- Test: `backend/tests/test_fusion.py`

This module is pure — data in, decision out, no I/O — so the arbitration logic can be tested
exhaustively without models or a database.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_fusion.py`:

```python
import pytest

from cardplatform.recognition.fusion import FusionConfig, fuse
from cardplatform.recognition.types import Candidate, OcrReading

# card_id -> collector number, as the catalog knows it
CATALOG = {
    "base1-4": "4",
    "base4-4": "4",
    "me2pt5-114": "114",
    "me2pt5-252": "252",
    "ex15-82": "82",
    "ex3-88": "88",
}


def numbers_for(card_ids):
    return {cid: CATALOG[cid] for cid in card_ids if cid in CATALOG}


def test_clear_visual_winner_with_ocr_agreement_is_confident():
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(
        candidates,
        OcrReading(collector_number="4", printed_total="102"),
        numbers_for(["base1-4", "base4-4"]),
    )

    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.confidence > 0.9


def test_ocr_breaks_a_visual_tie():
    """The measured real failure: same name, different print, margin 0.006.
    Visual alone picks wrong; the collector number settles it."""
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(
        candidates,
        OcrReading(collector_number="114"),
        numbers_for(["me2pt5-252", "me2pt5-114"]),
    )

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_ocr_promotes_a_lower_ranked_candidate():
    candidates = (Candidate("ex3-88", 0.79), Candidate("ex15-82", 0.78))

    result = fuse(candidates, OcrReading(collector_number="82"), numbers_for(["ex3-88", "ex15-82"]))

    assert result.card_id == "ex15-82"


def test_narrow_margin_without_ocr_is_ambiguous():
    candidates = (Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775))

    result = fuse(candidates, OcrReading(), numbers_for(["me2pt5-252", "me2pt5-114"]))

    assert result.status == "ambiguous"
    assert result.card_id is None
    assert len(result.candidates) == 2


def test_ocr_matching_nothing_falls_back_to_visual():
    """A misread number must not veto a confident visual match."""
    candidates = (Candidate("base1-4", 0.91), Candidate("base4-4", 0.60))

    result = fuse(
        candidates,
        OcrReading(collector_number="999"),
        numbers_for(["base1-4", "base4-4"]),
    )

    assert result.card_id == "base1-4"
    assert result.status == "confident"


def test_low_similarity_is_not_found():
    candidates = (Candidate("base1-4", 0.31), Candidate("base4-4", 0.29))

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]))

    assert result.status == "not_found"
    assert result.card_id is None


def test_no_candidates_is_not_found():
    result = fuse((), OcrReading(), {})

    assert result.status == "not_found"
    assert result.candidates == ()
    assert result.confidence == 0.0


def test_leading_zero_ocr_still_matches():
    candidates = (Candidate("base1-4", 0.70), Candidate("base4-4", 0.69))

    result = fuse(
        candidates, OcrReading(collector_number="004"), {"base1-4": "4", "base4-4": "4"}
    )

    # both share number 4, so OCR cannot disambiguate; margin is narrow -> ambiguous
    assert result.status == "ambiguous"


def test_visual_margin_is_reported():
    candidates = (Candidate("base1-4", 0.88), Candidate("base4-4", 0.61))

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]))

    assert result.visual_margin == pytest.approx(0.27, abs=1e-6)


def test_thresholds_are_configurable():
    candidates = (Candidate("base1-4", 0.60), Candidate("base4-4", 0.50))
    strict = FusionConfig(min_similarity=0.85)

    result = fuse(candidates, OcrReading(), numbers_for(["base1-4", "base4-4"]), config=strict)

    assert result.status == "not_found"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_fusion.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.fusion'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/fusion.py`:

```python
"""Combines the visual and OCR signals into one calibrated decision.

Why this exists, empirically: at a 2,993-card index, visual-only top-1 was 93.8% and
falling with scale, and every observed failure was a same-name/different-print pair
(Stunfisk ex -> Stunfisk ex, margin 0.006). The collector number resolves exactly those.

Meanwhile margin (top score minus runner-up) separates right from wrong: correct matches
averaged 0.081, incorrect ones 0.012. That is the signal `min_margin` thresholds on.

Defaults here are starting points. Task 11 calibrates them against real photographs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cardplatform.recognition.ocr import normalize_collector_number
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult


@dataclass(frozen=True)
class FusionConfig:
    # Below this top similarity, nothing plausible was found at all.
    min_similarity: float = 0.45
    # Above this margin the visual winner stands on its own.
    min_margin: float = 0.05
    # Confidence assigned when both signals agree.
    agreement_confidence: float = 0.97


def fuse(
    candidates: tuple[Candidate, ...],
    ocr: OcrReading,
    catalog_numbers: Mapping[str, str],
    config: FusionConfig | None = None,
) -> RecognitionResult:
    """Decide which candidate is the card, and how much to trust that.

    `catalog_numbers` maps each candidate's card_id to its collector number as printed
    in the catalog, so OCR can be checked against the shortlist.
    """
    config = config or FusionConfig()

    if not candidates:
        return RecognitionResult(
            card_id=None,
            confidence=0.0,
            status="not_found",
            candidates=(),
            ocr=ocr,
            visual_margin=0.0,
        )

    top = candidates[0]
    runner_up_score = candidates[1].visual_score if len(candidates) > 1 else 0.0
    margin = top.visual_score - runner_up_score

    if top.visual_score < config.min_similarity:
        return RecognitionResult(
            card_id=None,
            confidence=float(top.visual_score),
            status="not_found",
            candidates=candidates,
            ocr=ocr,
            visual_margin=margin,
        )

    # OCR arbitration: if the read number uniquely identifies one candidate, it wins
    # regardless of visual rank. This is the path that fixes same-artwork reprints.
    read_number = normalize_collector_number(ocr.collector_number)
    if read_number is not None:
        matches = [
            candidate
            for candidate in candidates
            if normalize_collector_number(catalog_numbers.get(candidate.card_id))
            == read_number
        ]
        if len(matches) == 1:
            return RecognitionResult(
                card_id=matches[0].card_id,
                confidence=config.agreement_confidence,
                status="confident",
                candidates=candidates,
                ocr=ocr,
                visual_margin=margin,
            )

    # No usable OCR: trust a clear visual winner, otherwise ask the user.
    if margin >= config.min_margin:
        return RecognitionResult(
            card_id=top.card_id,
            confidence=float(min(0.95, top.visual_score + margin)),
            status="confident",
            candidates=candidates,
            ocr=ocr,
            visual_margin=margin,
        )

    return RecognitionResult(
        card_id=None,
        confidence=float(top.visual_score),
        status="ambiguous",
        candidates=candidates,
        ocr=ocr,
        visual_margin=margin,
    )
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_fusion.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/fusion.py backend/tests/test_fusion.py && git commit -m "feat: add visual and ocr fusion with calibrated confidence"
```

---

## Task 9: Recognition service

**Files:**
- Create: `backend/src/cardplatform/recognition/service.py`
- Test: `backend/tests/test_recognition_service.py`

- [ ] **Step 1: Write the failing test**

The service is tested with fakes for the encoder, index, and OCR so it runs fast and deterministically.

`backend/tests/test_recognition_service.py`:

```python
import numpy as np
import pytest
from PIL import Image

from cardplatform.db.models import Card, CardSet
from cardplatform.recognition.service import RecognitionService
from cardplatform.recognition.types import Candidate, OcrReading


class FakeEncoder:
    dimension = 4

    def embed(self, image):
        return np.array([1, 0, 0, 0], dtype=np.float32)


class FakeIndex:
    def __init__(self, candidates):
        self._candidates = candidates
        self.searched = 0

    def search(self, vector, top_k):
        self.searched += 1
        return list(self._candidates)[:top_k]


class FakeReader:
    def __init__(self, reading=None):
        self._reading = reading or OcrReading()

    def read(self, image):
        return self._reading


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="me2pt5-114", set_id="base1", name="Stunfisk ex", number="114"))
    db.add(Card(id="me2pt5-252", set_id="base1", name="Stunfisk ex", number="252"))
    db.commit()
    return db


def _photo():
    return Image.new("RGB", (600, 825), (180, 40, 40))


def test_confident_match_returns_card(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
    )

    result = service.recognize(_photo(), rectify=False)

    assert result.status == "confident"
    assert result.card_id == "base1-4"


def test_ocr_disambiguates_same_name_reprints(seeded):
    """The real measured failure mode, end to end through the service."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775)]),
        reader=FakeReader(OcrReading(collector_number="114")),
    )

    result = service.recognize(_photo(), rectify=False)

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_ambiguous_result_returns_candidates(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775)]),
        reader=FakeReader(),
    )

    result = service.recognize(_photo(), rectify=False)

    assert result.status == "ambiguous"
    assert [c.card_id for c in result.candidates] == ["me2pt5-252", "me2pt5-114"]


def test_candidates_unknown_to_the_catalog_are_dropped(seeded):
    """An index entry for a card since removed from the catalog must not crash."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("ghost-1", 0.95), Candidate("base1-4", 0.60)]),
        reader=FakeReader(),
    )

    result = service.recognize(_photo(), rectify=False)

    assert all(c.card_id != "ghost-1" for c in result.candidates)


def test_rectification_failure_is_reported(seeded):
    """A photo with no detectable card returns not_found rather than guessing."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=FakeReader(),
    )
    blank = Image.new("RGB", (900, 700), (18, 18, 18))

    result = service.recognize(blank, rectify=True)

    assert result.status == "not_found"
    assert result.card_id is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.recognition.service'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/recognition/service.py`:

```python
"""Orchestrates the recognition pipeline: rectify, embed, search, OCR, fuse."""

from __future__ import annotations

import logging

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Card
from cardplatform.recognition.fusion import FusionConfig, fuse
from cardplatform.recognition.rectify import rectify_card
from cardplatform.recognition.types import OcrReading, RecognitionResult

logger = logging.getLogger(__name__)


class RecognitionService:
    def __init__(
        self,
        session: Session,
        encoder,
        index,
        reader,
        settings: Settings | None = None,
        fusion_config: FusionConfig | None = None,
    ) -> None:
        self.session = session
        self.encoder = encoder
        self.index = index
        self.reader = reader
        self.settings = settings or default_settings
        self.fusion_config = fusion_config

    def recognize(self, image: Image.Image, rectify: bool = True) -> RecognitionResult:
        """Identify the card in `image`.

        `rectify=False` is for callers that already rectified client-side (the Phase 1b
        PWA does this in WebAssembly for the live overlay).
        """
        working = image
        if rectify:
            flattened = rectify_card(image, size=self.settings.rectified_size)
            if flattened is None:
                logger.info("no card detected in frame")
                return RecognitionResult(
                    card_id=None,
                    confidence=0.0,
                    status="not_found",
                    candidates=(),
                    ocr=OcrReading(),
                    visual_margin=0.0,
                )
            working = flattened

        vector = self.encoder.embed(working)
        raw_candidates = self.index.search(vector, top_k=self.settings.visual_top_k)

        catalog_numbers = self._collector_numbers([c.card_id for c in raw_candidates])
        # Drop index entries the catalog no longer knows about.
        candidates = tuple(c for c in raw_candidates if c.card_id in catalog_numbers)

        reading = self.reader.read(working)
        return fuse(candidates, reading, catalog_numbers, config=self.fusion_config)

    def _collector_numbers(self, card_ids: list[str]) -> dict[str, str]:
        if not card_ids:
            return {}
        rows = self.session.execute(
            select(Card.id, Card.number).where(Card.id.in_(card_ids))
        ).all()
        return {card_id: number for card_id, number in rows}
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognition_service.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/recognition/service.py backend/tests/test_recognition_service.py && git commit -m "feat: add recognition service orchestrating the pipeline"
```

---

## Task 10: Build the real index and expose the API

**Files:**
- Modify: `backend/src/cardplatform/cli.py`
- Modify: `backend/src/cardplatform/api.py`
- Test: `backend/tests/test_recognize_api.py`

- [ ] **Step 1: Add the `build-index` CLI command**

In `backend/src/cardplatform/cli.py`, add this function:

```python
def build_index() -> int:
    """Download every catalog image, embed it, and persist a FAISS index."""
    from cardplatform.recognition.encoder import CardEncoder
    from cardplatform.recognition.images import ReferenceImageCache
    from cardplatform.recognition.index import CardIndex

    database = Database()
    database.create_all()
    cache = ReferenceImageCache(database.settings)
    encoder = CardEncoder(database.settings)

    with database.session() as session:
        rows = session.execute(
            select(Card.id, Card.image_small).where(Card.image_small.is_not(None))
        ).all()

    print(f"catalog: {len(rows)} cards with images")

    card_ids: list[str] = []
    images = []
    missing = 0
    for position, (card_id, url) in enumerate(rows, start=1):
        path = cache.fetch(card_id, url)
        if path is None:
            missing += 1
            continue
        image = cache.load(card_id)
        if image is None:
            missing += 1
            continue
        card_ids.append(card_id)
        images.append(image)
        if position % 500 == 0:
            print(f"  fetched {position}/{len(rows)} (missing so far: {missing})")

    print(f"embedding {len(images)} images...")
    vectors = encoder.embed_many(images)

    CardIndex(database.settings).build(card_ids, vectors).save()
    print(f"index built: {len(card_ids)} cards, {missing} unavailable")
    print(f"saved to {database.settings.index_path}")
    return 0
```

Add the required imports at the top of `cli.py`:

```python
from sqlalchemy import select

from cardplatform.db.models import Card
```

Register the subcommand inside `main`, alongside the existing ones:

```python
    sub.add_parser("build-index", help="Download card images and build the recognition index")
```

and add the dispatch branch:

```python
    if args.command == "build-index":
        return build_index()
```

- [ ] **Step 2: Run the real index build**

This downloads ~20,444 images (a few GB of traffic) and embeds them. Expect roughly 10–20 minutes
for downloads and under a minute for embedding on GPU.

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe build-index
```

Expected: `index built: ~20444 cards, <100 unavailable`, and a file at `data/card_index.faiss`
of roughly 42 MB. Re-running is cheap — cached images are skipped.

**If `missing` exceeds 500, stop and report it** rather than building a degraded index.

- [ ] **Step 3: Add the `/recognize` endpoint**

In `backend/src/cardplatform/api.py`, add these response models near the other Pydantic models:

```python
class CandidateOut(BaseModel):
    card_id: str
    name: str
    set_name: str
    number: str
    image_small: str | None
    visual_score: float


class RecognizeOut(BaseModel):
    status: str
    confidence: float
    visual_margin: float
    card: CardOut | None
    price: PriceOut | None
    candidates: list[CandidateOut]
    collector_number_read: str | None
```

Add a lazily-built recognition service as a **FastAPI dependency**, so tests can override it.
The heavy objects (CLIP weights, FAISS index) are cached module-level and built once; only the
thin `RecognitionService` wrapper is per-request, because it binds the request's DB session.

```python
_recognition_stack = None


def get_recognition_stack() -> dict:
    """Load CLIP weights and the FAISS index once per process.

    Building these per request would add seconds to every scan.
    """
    global _recognition_stack
    if _recognition_stack is None:
        from cardplatform.recognition.encoder import CardEncoder
        from cardplatform.recognition.index import CardIndex
        from cardplatform.recognition.ocr import CollectorNumberReader

        _recognition_stack = {
            "encoder": CardEncoder(),
            "index": CardIndex().load(),
            "reader": CollectorNumberReader(),
        }
    return _recognition_stack


def get_recognition_service(session: Session = Depends(get_session)):
    """Per-request recognition service bound to this request's session.

    Declared as a dependency so tests can override it with a stub and never load
    real model weights.
    """
    from cardplatform.recognition.service import RecognitionService

    stack = get_recognition_stack()
    return RecognitionService(
        session=session,
        encoder=stack["encoder"],
        index=stack["index"],
        reader=stack["reader"],
    )
```

Add the endpoint inside `create_app()`. Note `service` arrives via `Depends`, which is what makes
the test override work:

```python
    @app.post("/recognize", response_model=RecognizeOut)
    async def recognize(
        file: UploadFile = File(...),
        variant: str = Query(default="normal"),
        rectify: bool = Query(default=True),
        session: Session = Depends(get_session),
        service=Depends(get_recognition_service),
    ) -> RecognizeOut:
        import io

        from PIL import Image

        raw = await file.read()
        try:
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="unreadable image") from exc

        result = service.recognize(image, rectify=rectify)

        card_out = None
        price_out = None
        if result.card_id is not None:
            card = session.get(Card, result.card_id)
            if card is not None:
                card_out = _card_out(card)
                snapshot = PriceService(session).latest_price(result.card_id, variant)
                if snapshot is not None:
                    price_out = PriceOut(
                        source=snapshot.source,
                        variant=snapshot.variant,
                        low=snapshot.low,
                        mid=snapshot.mid,
                        high=snapshot.high,
                        market=snapshot.market,
                        source_updated_at=snapshot.source_updated_at,
                    )

        candidates_out: list[CandidateOut] = []
        for candidate in result.candidates:
            card = session.get(Card, candidate.card_id)
            if card is None:
                continue
            candidates_out.append(
                CandidateOut(
                    card_id=card.id,
                    name=card.name,
                    set_name=card.card_set.name if card.card_set else "",
                    number=card.number,
                    image_small=card.image_small,
                    visual_score=candidate.visual_score,
                )
            )

        return RecognizeOut(
            status=result.status,
            confidence=result.confidence,
            visual_margin=result.visual_margin,
            card=card_out,
            price=price_out,
            candidates=candidates_out,
            collector_number_read=result.ocr.collector_number,
        )
```

Add the required imports at the top of `api.py`:

```python
from fastapi import File, UploadFile

from cardplatform.prices.service import PriceService
```

Note: `PriceOut` already exists from Phase 0 and carries `source_updated_at`, so a recognized card's
price arrives with its staleness stamp intact.

- [ ] **Step 4: Write the API test**

`backend/tests/test_recognize_api.py`:

```python
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cardplatform.api import create_app, get_recognition_service, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult


class StubService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def recognize(self, image, rectify=True):
        self.calls.append(rectify)
        return self.result


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 82), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            image_small="https://images.pokemontcg.io/base1/4.png",
        )
    )
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="normal",
            market=800.43,
            source_updated_at="2026/07/29",
        )
    )
    db.commit()
    return db


def _client(db, result):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    stub = StubService(result)
    app.dependency_overrides[get_recognition_service] = lambda: stub
    return TestClient(app), stub


def test_confident_recognition_returns_card_and_price(seeded):
    result = RecognitionResult(
        card_id="base1-4",
        confidence=0.97,
        status="confident",
        candidates=(Candidate("base1-4", 0.91),),
        ocr=OcrReading(collector_number="4"),
        visual_margin=0.2,
    )
    client, _ = _client(seeded, result)

    response = client.post("/recognize", files={"file": ("card.png", _png(), "image/png")})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confident"
    assert body["card"]["name"] == "Charizard"
    assert body["price"]["market"] == 800.43
    assert body["price"]["source_updated_at"] == "2026/07/29"
    assert body["collector_number_read"] == "4"


def test_ambiguous_recognition_returns_candidates_without_a_card(seeded):
    result = RecognitionResult(
        card_id=None,
        confidence=0.78,
        status="ambiguous",
        candidates=(Candidate("base1-4", 0.781),),
        ocr=OcrReading(),
        visual_margin=0.006,
    )
    client, _ = _client(seeded, result)

    body = client.post("/recognize", files={"file": ("c.png", _png(), "image/png")}).json()

    assert body["status"] == "ambiguous"
    assert body["card"] is None
    assert body["candidates"][0]["card_id"] == "base1-4"
    assert body["candidates"][0]["name"] == "Charizard"


def test_not_found_returns_empty_candidates(seeded):
    result = RecognitionResult(
        card_id=None,
        confidence=0.0,
        status="not_found",
        candidates=(),
        ocr=OcrReading(),
        visual_margin=0.0,
    )
    client, _ = _client(seeded, result)

    body = client.post("/recognize", files={"file": ("c.png", _png(), "image/png")}).json()

    assert body["status"] == "not_found"
    assert body["candidates"] == []


def test_unreadable_upload_returns_400(seeded):
    result = RecognitionResult(None, 0.0, "not_found", (), OcrReading(), 0.0)
    client, _ = _client(seeded, result)

    response = client.post("/recognize", files={"file": ("x.png", b"not-an-image", "image/png")})

    assert response.status_code == 400


def test_rectify_flag_is_passed_through(seeded):
    result = RecognitionResult(None, 0.0, "not_found", (), OcrReading(), 0.0)
    client, stub = _client(seeded, result)

    client.post(
        "/recognize", params={"rectify": "false"}, files={"file": ("c.png", _png(), "image/png")}
    )

    assert stub.calls == [False]
```

**Why these tests never load model weights:** they override `get_recognition_service` in
`app.dependency_overrides`, so `get_recognition_stack()` is never called. That keeps the API tests
fast and runnable without a built index — which matters, because the index is a 42 MB artifact that
is deliberately gitignored.

Add `python-multipart` to the `ml` extra in `pyproject.toml` — FastAPI requires it for
`UploadFile`, and without it the tests fail at import with a clear error.

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_recognize_api.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Verify against the real index and a real card photo**

Start the server:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --port 8000
```

Download a reference image and POST it back (this is a sanity check, not a real-photo test):

```bash
curl -s -o /tmp/charizard.png https://images.pokemontcg.io/base1/4_hires.png && curl -s -X POST "http://127.0.0.1:8000/recognize?rectify=false" -F "file=@/tmp/charizard.png" | python -m json.tool
```

Expected: `"status": "confident"`, `"card"` naming Charizard from Base, and a `price` block with a
`source_updated_at`. Paste the real JSON. Then stop the server.

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/cli.py backend/src/cardplatform/api.py backend/tests/test_recognize_api.py backend/pyproject.toml && git commit -m "feat: add index build command and recognize endpoint"
```

---

## Task 11: Evaluation harness and threshold calibration

This is the task that answers "does it actually work", and it is the reason the earlier tasks
avoided baking in magic numbers.

**Files:**
- Create: `backend/scripts/evaluate_recognition.py`

- [ ] **Step 1: Write the harness**

`backend/scripts/evaluate_recognition.py`:

```python
"""Measures recognition accuracy at full catalog scale and calibrates the confidence threshold.

Research at a 2,993-card index measured 93.8% top-1 / 97.5% top-3 under degradation, with
accuracy falling as the index grew. This script establishes the real numbers at 20,444 and
finds the margin threshold that best separates correct from incorrect matches.
"""

import argparse
import io
import random
import sys
import time

import httpx
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from sqlalchemy import select

from cardplatform.db.models import Card
from cardplatform.db.session import Database
from cardplatform.recognition.encoder import CardEncoder
from cardplatform.recognition.index import CardIndex

DEGRADATIONS = ("clean", "jpeg", "blur", "dim", "combo")


def degrade(image: Image.Image, mode: str) -> Image.Image:
    if mode == "clean":
        return image
    if mode == "jpeg":
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=35)
        return Image.open(buf).convert("RGB")
    if mode == "blur":
        return image.filter(ImageFilter.GaussianBlur(1.6))
    if mode == "dim":
        return ImageEnhance.Brightness(image).enhance(0.55)
    if mode == "combo":
        out = image.filter(ImageFilter.GaussianBlur(1.1))
        out = ImageEnhance.Brightness(out).enhance(0.7)
        out = out.rotate(3, expand=False, fillcolor=(20, 20, 20))
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=45)
        return Image.open(buf).convert("RGB")
    raise ValueError(mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=500)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    database = Database()
    encoder = CardEncoder(database.settings)
    index = CardIndex(database.settings).load()
    print(f"index: {index.size} cards")

    with database.session() as session:
        rows = session.execute(
            select(Card.id, Card.image_small).where(Card.image_small.is_not(None))
        ).all()
    sample = random.sample(rows, min(args.sample, len(rows)))

    print(f"downloading {len(sample)} query images...")
    images, truth = [], []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for card_id, url in sample:
            try:
                raw = client.get(url).content
                images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
                truth.append(card_id)
            except Exception:
                pass
    print(f"got {len(images)}")

    print(f"\n{'condition':<10}{'top-1':>9}{'top-3':>9}{'margin(ok)':>12}{'margin(bad)':>13}")
    print("-" * 53)
    all_margins, all_correct = [], []
    for mode in DEGRADATIONS:
        t0 = time.time()
        queries = [degrade(im, mode) for im in images]
        vectors = encoder.embed_many(queries)
        hits1 = hits3 = 0
        margins, correct_flags = [], []
        for vector, expected in zip(vectors, truth):
            candidates = index.search(vector, top_k=3)
            ids = [c.card_id for c in candidates]
            is_top1 = bool(ids) and ids[0] == expected
            hits1 += is_top1
            hits3 += expected in ids
            margin = (
                candidates[0].visual_score - candidates[1].visual_score
                if len(candidates) > 1
                else 1.0
            )
            margins.append(margin)
            correct_flags.append(is_top1)
        margins = np.array(margins)
        flags = np.array(correct_flags)
        all_margins.append(margins)
        all_correct.append(flags)
        ok = margins[flags].mean() if flags.any() else float("nan")
        bad = margins[~flags].mean() if (~flags).any() else float("nan")
        print(
            f"{mode:<10}{hits1/len(truth):>8.1%}{hits3/len(truth):>9.1%}"
            f"{ok:>12.3f}{bad:>13.3f}   ({time.time()-t0:.0f}s)"
        )

    margins = np.concatenate(all_margins)
    flags = np.concatenate(all_correct)

    print("\n=== threshold calibration ===")
    print("Choosing min_margin: above it we auto-confirm, below it we ask the user.")
    print(f"{'threshold':>10}{'auto-confirm %':>16}{'precision':>12}{'wrong auto':>12}")
    print("-" * 50)
    best = None
    for threshold in np.arange(0.01, 0.16, 0.01):
        auto = margins >= threshold
        if auto.sum() == 0:
            continue
        precision = flags[auto].mean()
        wrong = int((~flags[auto]).sum())
        print(f"{threshold:>10.2f}{auto.mean():>15.1%}{precision:>12.1%}{wrong:>12}")
        # Prefer the lowest threshold that keeps auto-confirm precision >= 99%.
        if precision >= 0.99 and best is None:
            best = threshold
    if best is not None:
        print(f"\nRECOMMENDED FusionConfig.min_margin = {best:.2f}")
        print("(lowest threshold holding >=99% precision on auto-confirmed matches)")
    else:
        print("\nNo threshold reached 99% precision — rely more heavily on OCR arbitration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the evaluation**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe backend/scripts/evaluate_recognition.py --sample 500
```

Paste the full real output. Expect top-1 to be **meaningfully lower than the 93.8% measured at
2,993 cards** — that drop is the expected consequence of a 7× larger index and is exactly why OCR
arbitration exists.

- [ ] **Step 3: Apply the calibrated threshold**

Update `FusionConfig.min_margin` in `backend/src/cardplatform/recognition/fusion.py` to the
recommended value from Step 2, and replace the default's comment with the measured basis, e.g.:

```python
    # Calibrated against a 500-card sample at full index scale (record the date you
    # ran it): the lowest margin holding >=99% precision on auto-confirmed matches.
    min_margin: float = 0.07
```

Re-run the fusion tests to confirm nothing broke:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_fusion.py -v
```

If the new threshold breaks a fusion test, fix the **test's** fixture values to straddle the real
threshold rather than weakening the threshold — the calibration is evidence, the test fixtures were
guesses.

- [ ] **Step 4: Run the full suite**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass. The suite was 69 before this plan; expect roughly 120.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/evaluate_recognition.py backend/src/cardplatform/recognition/fusion.py backend/tests/test_fusion.py && git commit -m "feat: add recognition evaluation harness and calibrate confidence threshold"
```

---

## Task 12: Update project docs

**Files:**
- Modify: `PROJECT.md`
- Modify: `docs/index.html`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Record the measured results in `PROJECT.md`**

Add a "Phase 1a — shipped" section mirroring the existing "Phase 0 — shipped" one. Include the
**real** top-1/top-3 numbers from Task 11 at full index scale, the calibrated `min_margin`, and how
many cards are in the index. Do not copy the research-phase numbers — use what Task 11 actually
measured.

- [ ] **Step 2: Update the roadmap status**

In `PROJECT.md`, change the Phase 1 row to note that the recognition engine is complete and the PWA
(Phase 1b) is next.

In `docs/index.html`, change the Phase 01 row's status chip from
`<span class="st now">Next</span>` to `<span class="st done">Engine complete</span>`, and update the
header tag text to reflect recognition being live.

- [ ] **Step 3: Add recognition commands to `CLAUDE.md`**

Under `## Commands`, add:

```
- Build the recognition index: `C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe build-index` (downloads ~20k images; re-runs skip cached)
- Evaluate recognition accuracy: `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe backend/scripts/evaluate_recognition.py --sample 500`
```

Under `## Conventions`, add:

```
- **Install torch and torchvision together from the cu128 index**, and re-run that install after any package that depends on torch. `pip install open-clip-torch` silently replaces the CUDA build with a CPU one, and repairing torch alone breaks torchvision (`operator torchvision::nms does not exist`).
- **Never derive a cache filename from an image URL.** 661 catalog images have no file extension. Key on `card_id`.
- **Recognition must report uncertainty, never guess.** Visual matching alone is ~85% top-1 at full catalog scale; OCR arbitration and the `ambiguous` status are what make it trustworthy.
```

- [ ] **Step 4: Commit and push**

```bash
git add PROJECT.md docs/index.html CLAUDE.md && git commit -m "docs: record phase 1a recognition results" && git push origin HEAD
```

---

## Definition of done

- [ ] `pytest` passes with no failures (~120 tests).
- [ ] `cardplatform build-index` produced an index of ~20,400 cards at `data/card_index.faiss`.
- [ ] `evaluate_recognition.py` reported real top-1/top-3 at full scale, and `min_margin` is set from
      that measurement rather than a guess.
- [ ] `POST /recognize` returns a confident identification for a clean reference image, with a price
      carrying its `source_updated_at`.
- [ ] An ambiguous input returns `status: "ambiguous"` with ranked candidates instead of a wrong
      confident answer.
- [ ] `data/reference_images/` and `data/card_index.faiss` are gitignored and uncommitted.

## Known limitation to carry into Phase 1b

**Everything measured so far uses degraded *reference images*, not photographs of physical cards.**
Real photos add perspective, uneven lighting, background clutter, and physical foil glare that no
augmentation here simulates. Expect accuracy to drop again on real camera input.

Phase 1b's first task should therefore be to **collect a small labelled set of real phone photos**
(30–50 cards, varied lighting and angle) and re-run `evaluate_recognition.py` against them. That is
the honest accuracy number, and it is the one that should drive any decision to fine-tune the
encoder.
