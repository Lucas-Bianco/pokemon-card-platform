# Phase 1b — Scan PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Point a phone at a Pokémon card and see what it is and what it's worth — and capture enough real-world data from doing so to finally measure how well recognition actually works.

**Architecture:** A React PWA served over HTTPS by Vite (mandatory: the camera API refuses to run otherwise), proxying to the existing FastAPI backend. Capture through a static framing guide, POST to `/recognize`, show the card immediately and fetch its price separately. Every scan is logged with its image and outcome, and every user correction becomes a labelled example.

**Tech Stack:** React 19 + TypeScript + Vite 8, `@vitejs/plugin-basic-ssl`, `vite-plugin-pwa`, Vitest, on the existing Python 3.12 / FastAPI backend.

---

## Scope

Phase 1a built the engine. This phase builds the thing a human actually touches, plus the two backend
gaps that make it useful. It ends with **real measured accuracy on photographs of physical cards** —
the one number the project still does not have.

**Not in scope:** the OpenCV.js live-detection overlay (10 MB WASM). A static framing guide gives
identical recognition accuracy because the server does the real rectification, and it nudges the user
toward the framing that works best. Deferred to its own phase if wanted.

---

## Three constraints discovered before planning — do not re-derive

### 1. The camera will not work over plain HTTP

`getUserMedia` requires a **secure context**. On `http://10.0.0.175:5173` from a phone, the camera is
blocked outright — not a permission prompt, a hard refusal. Only HTTPS or `localhost` qualify.

So the dev server **must** run HTTPS via `@vitejs/plugin-basic-ssl` (v2.3.0), and the phone must
accept the self-signed certificate warning once. Task 4 covers this. Getting it wrong means a blank
camera view with a console error that does not obviously point at TLS.

### 2. An HTTPS page cannot call the HTTP API — proxy, don't CORS

Once the PWA is on `https://…:5173`, a `fetch` to `http://…:8000` is **mixed content** and is blocked
by the browser regardless of CORS headers. The fix is Vite's dev-server proxy: the browser only ever
talks HTTPS to Vite, and Vite forwards to the backend server-side. Configure `/api` → `http://127.0.0.1:8000`.
Do not attempt to solve this with CORS headers; CORS is not the problem.

### 3. Almost nothing has a price yet

Measured: **2 of 20,444 cards have any price snapshot** (0.0098% coverage). A scan today shows
"unpriced" essentially always, which makes the whole value proposition invisible.

On-demand fetching works — 5 of 5 test cards succeeded — but is slow: **4.3 s mean, 9.1 s worst
case**, because the upstream API returns HTTP 500 frequently and the client backs off.

That timing dictates the design: **`/recognize` must not block on price.** It returns the card and
any cached price immediately; the UI renders the card, then asks for the price separately and shows
a spinner on just that line. Coupling them would make every first-time scan feel broken.

---

## File structure

```
backend/src/cardplatform/
  db/models.py            # + ScanLog
  scans/__init__.py
  scans/store.py          # ScanStore: record a scan, apply a correction, list history
  api.py                  # + price endpoints, + scan endpoints
backend/tests/
  test_scan_store.py
  test_price_api.py
  test_scan_api.py

frontend/
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  public/manifest.webmanifest
  src/
    main.tsx
    App.tsx
    styles.css
    api/types.ts          # mirrors the backend response shapes
    api/client.ts         # every network call, one place
    components/
      CameraCapture.tsx   # video element, framing guide, shutter
      ScanResult.tsx      # confident / not_found rendering + price line
      CandidatePicker.tsx # the ambiguous case: pick from ranked candidates
      PriceLine.tsx       # price with staleness, own loading state
    lib/
      format.ts           # pure display helpers
  src/__tests__/
    client.test.ts
    format.test.ts
```

`api/client.ts` is the only module that talks to the network, so every component is testable without
mocking `fetch` in five places.

---

## Task 1: ScanLog model

**Files:**
- Modify: `backend/src/cardplatform/db/models.py`
- Test: `backend/tests/test_scan_store.py` (model portion)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scan_store.py` with just the model tests for now:

```python
from datetime import datetime, timezone

from cardplatform.db.models import Card, CardSet, ScanLog


def _seed(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def test_scan_log_persists_a_prediction(db):
    _seed(db)
    db.add(
        ScanLog(
            image_path="scans/abc.png",
            predicted_card_id="base1-4",
            status="confident",
            confidence=0.97,
            visual_margin=0.14,
            collector_number_read="4",
        )
    )
    db.commit()

    row = db.query(ScanLog).one()
    assert row.predicted_card_id == "base1-4"
    assert row.corrected_card_id is None
    assert row.created_at.tzinfo is not None


def test_scan_log_accepts_a_correction(db):
    _seed(db)
    scan = ScanLog(image_path="scans/abc.png", predicted_card_id="base1-4", status="confident")
    db.add(scan)
    db.commit()

    scan.corrected_card_id = "base4-4"
    db.commit()

    assert db.query(ScanLog).one().corrected_card_id == "base4-4"


def test_scan_log_allows_a_prediction_of_nothing(db):
    """A not_found scan is still worth logging — those are the interesting failures."""
    _seed(db)
    db.add(ScanLog(image_path="scans/x.png", predicted_card_id=None, status="not_found"))
    db.commit()

    assert db.query(ScanLog).one().predicted_card_id is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_scan_store.py -v
```

Expected: FAIL — `ImportError: cannot import name 'ScanLog'`

- [ ] **Step 3: Add the model**

In `backend/src/cardplatform/db/models.py`, add at the end of the file:

```python
class ScanLog(Base):
    """One recognition attempt, kept for evaluation and future fine-tuning.

    This is the project's only source of labelled real-world data: the spec's plan for
    improving accuracy over time depends on users correcting wrong answers, and a
    correction is only useful if the image that produced it was kept.
    """

    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_path: Mapped[str] = mapped_column(String)
    predicted_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("cards.id"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(String, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    visual_margin: Mapped[float | None] = mapped_column(Float, default=None)
    collector_number_read: Mapped[str | None] = mapped_column(String, default=None)
    # Set when the user says the prediction was wrong. NULL means "not reviewed",
    # which is deliberately different from "confirmed correct".
    corrected_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("cards.id"), index=True, default=None
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

Add `Boolean` to the existing `sqlalchemy` import line at the top of the file.

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_scan_store.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/db/models.py backend/tests/test_scan_store.py && git commit -m "feat: add scan log model for recognition evaluation"
```

---

## Task 2: Scan store

**Files:**
- Create: `backend/src/cardplatform/scans/__init__.py` (empty)
- Create: `backend/src/cardplatform/scans/store.py`
- Modify: `backend/src/cardplatform/config.py` (add `scan_image_dir`)
- Test: `backend/tests/test_scan_store.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scan_store.py`:

```python
import io

import pytest
from PIL import Image

from cardplatform.config import Settings
from cardplatform.scans.store import ScanStore


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 82), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


def test_settings_expose_scan_dir(tmp_path):
    assert Settings(data_dir=tmp_path).scan_image_dir == tmp_path / "scans"


def test_record_writes_the_image_and_the_row(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))

    scan = store.record(
        image_bytes=_png(),
        predicted_card_id="base1-4",
        status="confident",
        confidence=0.97,
        visual_margin=0.14,
        collector_number_read="4",
    )

    assert scan.id is not None
    saved = tmp_path / scan.image_path
    assert saved.exists()
    assert Image.open(saved).size == (60, 82)


def test_recorded_image_paths_are_unique(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))

    first = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    second = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    assert first.image_path != second.image_path


def test_confirm_marks_the_prediction_correct(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    store.confirm(scan.id)

    assert store.get(scan.id).confirmed is True
    assert store.get(scan.id).corrected_card_id is None


def test_correct_records_the_real_card(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="ambiguous")

    store.correct(scan.id, "base4-4")

    stored = store.get(scan.id)
    assert stored.corrected_card_id == "base4-4"
    assert stored.confirmed is True


def test_correcting_to_an_unknown_card_is_rejected(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    with pytest.raises(ValueError, match="unknown card"):
        store.correct(scan.id, "nope-1")


def test_accuracy_counts_only_reviewed_scans(db, tmp_path):
    """An unreviewed scan is not evidence either way — that is the whole point of
    keeping `confirmed` separate from `corrected_card_id`."""
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    right = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    wrong = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")  # unreviewed

    store.confirm(right.id)
    store.correct(wrong.id, "base4-4")

    stats = store.accuracy()
    assert stats.reviewed == 2
    assert stats.correct == 1
    assert stats.top1_accuracy == pytest.approx(0.5)


def test_accuracy_with_no_reviews_is_zero_not_a_crash(db, tmp_path):
    _seed(db)
    stats = ScanStore(db, Settings(data_dir=tmp_path)).accuracy()

    assert stats.reviewed == 0
    assert stats.top1_accuracy == 0.0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_scan_store.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.scans'`

- [ ] **Step 3: Add the setting**

In `backend/src/cardplatform/config.py`, add alongside the other path properties:

```python
    @property
    def scan_image_dir(self) -> Path:
        return self.data_dir / "scans"
```

- [ ] **Step 4: Write the store**

`backend/src/cardplatform/scans/__init__.py`: create as an empty file.

`backend/src/cardplatform/scans/store.py`:

```python
"""Persists recognition attempts so accuracy can be measured on real photographs.

Everything measured so far used degraded reference images. This store is how the
project finally learns what happens with a phone camera pointed at a physical card.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Card, ScanLog


@dataclass(frozen=True)
class ScanAccuracy:
    reviewed: int
    correct: int
    top1_accuracy: float


class ScanStore:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or default_settings
        self.directory = self.settings.scan_image_dir
        self.directory.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        image_bytes: bytes,
        status: str,
        predicted_card_id: str | None = None,
        confidence: float | None = None,
        visual_margin: float | None = None,
        collector_number_read: str | None = None,
    ) -> ScanLog:
        # uuid rather than a counter: two scans in the same second must not collide,
        # and the filename should not depend on database state.
        name = f"{uuid.uuid4().hex}.png"
        (self.directory / name).write_bytes(image_bytes)

        scan = ScanLog(
            image_path=f"scans/{name}",
            predicted_card_id=predicted_card_id,
            status=status,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
        )
        self.session.add(scan)
        self.session.commit()
        return scan

    def get(self, scan_id: int) -> ScanLog | None:
        return self.session.get(ScanLog, scan_id)

    def confirm(self, scan_id: int) -> ScanLog | None:
        scan = self.get(scan_id)
        if scan is None:
            return None
        scan.confirmed = True
        self.session.commit()
        return scan

    def correct(self, scan_id: int, card_id: str) -> ScanLog | None:
        scan = self.get(scan_id)
        if scan is None:
            return None
        if self.session.get(Card, card_id) is None:
            raise ValueError(f"unknown card: {card_id}")
        scan.corrected_card_id = card_id
        scan.confirmed = True
        self.session.commit()
        return scan

    def recent(self, limit: int = 50) -> list[ScanLog]:
        return list(
            self.session.scalars(
                select(ScanLog).order_by(ScanLog.created_at.desc()).limit(limit)
            ).all()
        )

    def accuracy(self) -> ScanAccuracy:
        """Top-1 accuracy over reviewed scans only.

        An unreviewed scan is not evidence in either direction, so it is excluded
        rather than silently counted as a success.
        """
        reviewed = list(
            self.session.scalars(select(ScanLog).where(ScanLog.confirmed.is_(True))).all()
        )
        if not reviewed:
            return ScanAccuracy(reviewed=0, correct=0, top1_accuracy=0.0)
        correct = sum(1 for s in reviewed if s.corrected_card_id is None)
        return ScanAccuracy(
            reviewed=len(reviewed),
            correct=correct,
            top1_accuracy=correct / len(reviewed),
        )
```

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_scan_store.py -v
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/scans backend/src/cardplatform/config.py backend/tests/test_scan_store.py && git commit -m "feat: add scan store for real-photo accuracy measurement"
```

---

## Task 3: Price and scan API endpoints

**Files:**
- Modify: `backend/src/cardplatform/api.py`
- Test: `backend/tests/test_price_api.py`
- Test: `backend/tests/test_scan_api.py`

Two gaps close here. The Phase 0 review flagged that **no endpoint returns the *resolved* price** —
`/cards/{id}/prices` returns every source/variant pair and leaves the "which is *the* price" rule
stranded in `PriceService`. And nothing can fetch a price on demand, which is why coverage is 0.0098%.

- [ ] **Step 1: Write the failing price tests**

`backend/tests/test_price_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_price_provider, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.prices.provider import PriceQuote


class StubProvider:
    name = "stub"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch(self, card_id):
        self.calls.append(card_id)
        return [q for q in self.quotes if q.card_id == card_id]


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
    db.commit()
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=800.43,
            source_updated_at="2026/07/29",
        )
    )
    db.commit()
    return db


def _client(db, provider=None):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    stub = provider or StubProvider([])
    app.dependency_overrides[get_price_provider] = lambda: stub
    return TestClient(app), stub


def test_resolved_price_returns_the_cached_snapshot(seeded):
    client, _ = _client(seeded)

    response = client.get("/cards/base1-4/price", params={"variant": "holofoil"})

    assert response.status_code == 200
    body = response.json()
    assert body["market"] == 800.43
    assert body["source"] == "tcgplayer"
    assert body["source_updated_at"] == "2026/07/29"


def test_resolved_price_is_204_when_unpriced(seeded):
    """A card with no price is a normal state, not an error."""
    client, _ = _client(seeded)

    assert client.get("/cards/base1-58/price").status_code == 204


def test_resolved_price_404s_for_an_unknown_card(seeded):
    client, _ = _client(seeded)

    assert client.get("/cards/nope-1/price").status_code == 404


def test_refresh_fetches_and_returns_the_new_price(seeded):
    provider = StubProvider(
        [PriceQuote("base1-58", "tcgplayer", "normal", market=12.5, source_updated_at="2026/07/29")]
    )
    client, stub = _client(seeded, provider)

    response = client.post("/cards/base1-58/prices/refresh", params={"variant": "normal"})

    assert response.status_code == 200
    assert response.json()["market"] == 12.5
    assert stub.calls == ["base1-58"]


def test_refresh_returns_204_when_the_source_has_nothing(seeded):
    client, _ = _client(seeded, StubProvider([]))

    assert client.post("/cards/base1-58/prices/refresh").status_code == 204


def test_refresh_404s_for_an_unknown_card(seeded):
    client, _ = _client(seeded)

    assert client.post("/cards/nope-1/prices/refresh").status_code == 404
```

- [ ] **Step 2: Write the failing scan tests**

`backend/tests/test_scan_api.py`:

```python
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 82), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def _record(client, status="confident", predicted="base1-4"):
    return client.post(
        "/scans",
        params={"status": status, "predicted_card_id": predicted, "confidence": 0.97},
        files={"file": ("scan.png", _png(), "image/png")},
    )


def test_recording_a_scan_returns_its_id(client):
    response = _record(client)

    assert response.status_code == 201
    assert isinstance(response.json()["id"], int)


def test_confirming_a_scan_marks_it_correct(client):
    scan_id = _record(client).json()["id"]

    response = client.post(f"/scans/{scan_id}/confirm")

    assert response.status_code == 200
    assert response.json()["confirmed"] is True
    assert response.json()["corrected_card_id"] is None


def test_correcting_a_scan_records_the_real_card(client):
    scan_id = _record(client).json()["id"]

    response = client.post(f"/scans/{scan_id}/correct", params={"card_id": "base4-4"})

    assert response.status_code == 200
    assert response.json()["corrected_card_id"] == "base4-4"


def test_correcting_to_an_unknown_card_is_404(client):
    scan_id = _record(client).json()["id"]

    assert client.post(f"/scans/{scan_id}/correct", params={"card_id": "nope-1"}).status_code == 404


def test_correcting_a_missing_scan_is_404(client):
    assert client.post("/scans/9999/correct", params={"card_id": "base1-4"}).status_code == 404


def test_accuracy_reports_reviewed_scans_only(client):
    right = _record(client).json()["id"]
    wrong = _record(client).json()["id"]
    _record(client)  # left unreviewed

    client.post(f"/scans/{right}/confirm")
    client.post(f"/scans/{wrong}/correct", params={"card_id": "base4-4"})

    body = client.get("/scans/accuracy").json()
    assert body["reviewed"] == 2
    assert body["correct"] == 1
    assert body["top1_accuracy"] == 0.5


def test_recent_scans_are_listed_newest_first(client):
    _record(client, predicted="base1-4")
    _record(client, predicted="base4-4")

    body = client.get("/scans").json()

    assert len(body) == 2
    assert body[0]["predicted_card_id"] == "base4-4"
```

- [ ] **Step 3: Run both, verify they fail**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_api.py backend/tests/test_scan_api.py -v
```

Expected: FAIL — `ImportError: cannot import name 'get_price_provider'`

- [ ] **Step 4: Implement the endpoints**

In `backend/src/cardplatform/api.py`, add the provider dependency near the other dependencies:

```python
def get_price_provider():
    """The live price source. A dependency so tests can stub it out — the real one
    talks to an API measured at roughly a 17% success rate."""
    from cardplatform.prices.pokemontcg import PokemonTcgIoProvider

    return PokemonTcgIoProvider()
```

Add these response models alongside the existing ones:

```python
class ScanOut(BaseModel):
    id: int
    status: str
    predicted_card_id: str | None
    corrected_card_id: str | None
    confirmed: bool
    confidence: float | None
    visual_margin: float | None
    collector_number_read: str | None


class ScanAccuracyOut(BaseModel):
    reviewed: int
    correct: int
    top1_accuracy: float
```

Add a shared helper next to the other module-level helpers:

```python
def _price_out(snapshot) -> PriceOut:  # noqa: ANN001
    return PriceOut(
        source=snapshot.source,
        variant=snapshot.variant,
        low=snapshot.low,
        mid=snapshot.mid,
        high=snapshot.high,
        market=snapshot.market,
        source_updated_at=snapshot.source_updated_at,
    )


def _scan_out(scan) -> ScanOut:  # noqa: ANN001
    return ScanOut(
        id=scan.id,
        status=scan.status,
        predicted_card_id=scan.predicted_card_id,
        corrected_card_id=scan.corrected_card_id,
        confirmed=scan.confirmed,
        confidence=scan.confidence,
        visual_margin=scan.visual_margin,
        collector_number_read=scan.collector_number_read,
    )
```

Add these endpoints inside `create_app()`:

```python
    @app.get("/cards/{card_id}/price")
    def resolved_price(
        card_id: str,
        variant: str = Query(default="normal"),
        session: Session = Depends(get_session),
    ) -> Response:
        """The single price to show for this card and variant, or 204 if unpriced.

        `/cards/{id}/prices` returns every source and variant; this applies the
        tcgplayer-then-cardmarket resolution rule so callers do not reimplement it.

        Returns a bare Response rather than declaring a response_model: a 204 must
        carry no body, and returning `None` under a response_model would serialise a
        literal `null`, which is not a valid 204.
        """
        _require_card(session, card_id)
        snapshot = PriceService(session).latest_price(card_id, variant)
        if snapshot is None:
            return Response(status_code=204)
        return JSONResponse(_price_out(snapshot).model_dump())

    @app.post("/cards/{card_id}/prices/refresh")
    def refresh_price(
        card_id: str,
        variant: str = Query(default="normal"),
        session: Session = Depends(get_session),
        provider=Depends(get_price_provider),
    ) -> Response:
        """Fetch this card's price from the live source now.

        Measured 4.3 s mean and 9.1 s worst case, because the upstream API fails
        often and the client backs off. Callers should not block a scan on this.
        """
        _require_card(session, card_id)
        PriceService(session, provider).refresh_card(card_id)
        snapshot = PriceService(session).latest_price(card_id, variant)
        if snapshot is None:
            return Response(status_code=204)
        return JSONResponse(_price_out(snapshot).model_dump())

    @app.post("/scans", response_model=ScanOut, status_code=201)
    async def record_scan(
        file: UploadFile = File(...),
        status: str = Query(...),
        predicted_card_id: str | None = Query(default=None),
        confidence: float | None = Query(default=None),
        visual_margin: float | None = Query(default=None),
        collector_number_read: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> ScanOut:
        scan = ScanStore(session).record(
            image_bytes=await file.read(),
            status=status,
            predicted_card_id=predicted_card_id,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
        )
        return _scan_out(scan)

    @app.post("/scans/{scan_id}/confirm", response_model=ScanOut)
    def confirm_scan(scan_id: int, session: Session = Depends(get_session)) -> ScanOut:
        scan = ScanStore(session).confirm(scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="unknown scan")
        return _scan_out(scan)

    @app.post("/scans/{scan_id}/correct", response_model=ScanOut)
    def correct_scan(
        scan_id: int,
        card_id: str = Query(...),
        session: Session = Depends(get_session),
    ) -> ScanOut:
        store = ScanStore(session)
        try:
            scan = store.correct(scan_id, card_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if scan is None:
            raise HTTPException(status_code=404, detail="unknown scan")
        return _scan_out(scan)

    @app.get("/scans", response_model=list[ScanOut])
    def list_scans(
        limit: int = Query(default=50, le=200), session: Session = Depends(get_session)
    ) -> list[ScanOut]:
        return [_scan_out(s) for s in ScanStore(session).recent(limit)]

    @app.get("/scans/accuracy", response_model=ScanAccuracyOut)
    def scan_accuracy(session: Session = Depends(get_session)) -> ScanAccuracyOut:
        stats = ScanStore(session).accuracy()
        return ScanAccuracyOut(
            reviewed=stats.reviewed, correct=stats.correct, top1_accuracy=stats.top1_accuracy
        )
```

Add to the imports at the top of `api.py`:

```python
from fastapi import Response
from fastapi.responses import JSONResponse

from cardplatform.scans.store import ScanStore
```

**Route-ordering note:** FastAPI matches routes in declaration order, so `/scans/accuracy` must be
declared **before** any `/scans/{scan_id}` route that could swallow it. Declare it last as written
above only if `scan_id` is typed `int` (FastAPI will 422 on `"accuracy"`, not match it). If you see
a 422 from `/scans/accuracy`, move that route above the parameterised ones.

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_api.py backend/tests/test_scan_api.py -v
```

Expected: 6 + 7 = 13 passed.

- [ ] **Step 6: Run the full suite**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass, roughly 179.

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/api.py backend/tests/test_price_api.py backend/tests/test_scan_api.py && git commit -m "feat: add resolved-price, on-demand refresh, and scan logging endpoints"
```

---

## Task 4: Frontend scaffold with HTTPS and proxy

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/public/manifest.webmanifest`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css`
- Modify: `.gitignore`

- [ ] **Step 1: Ignore node_modules first**

Add to the root `.gitignore` before installing anything, so a 200 MB directory is never staged:

```
# ---- Frontend ----
node_modules/
frontend/dist/
frontend/.vite/
*.local
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "cardplatform-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^19.2.0",
    "react-dom": "^19.2.0"
  },
  "devDependencies": {
    "@testing-library/react": "^16.3.0",
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "@vitejs/plugin-basic-ssl": "^2.3.0",
    "@vitejs/plugin-react": "^6.0.0",
    "jsdom": "^30.0.0",
    "typescript": "~5.9.0",
    "vite": "^8.1.0",
    "vite-plugin-pwa": "^1.3.0",
    "vitest": "^4.1.0"
  }
}
```

- [ ] **Step 3: Write `frontend/vite.config.ts`**

This file is where both hard constraints get solved. Do not simplify it.

```ts
import basicSsl from "@vitejs/plugin-basic-ssl";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    // getUserMedia refuses to run outside a secure context. Over plain HTTP on a
    // phone the camera is blocked outright — not a prompt, a hard refusal. This
    // serves a self-signed cert so the LAN address qualifies.
    basicSsl(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: false, // supplied by public/manifest.webmanifest
    }),
  ],
  server: {
    host: true, // listen on the LAN so a phone can reach it
    port: 5173,
    proxy: {
      // An HTTPS page cannot fetch an HTTP API — that is mixed content, and no CORS
      // header fixes it. Proxying keeps the browser on HTTPS while Vite talks to the
      // backend server-side.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

- [ ] **Step 4: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vite/client", "vitest/globals"]
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#0b0d12" />
    <link rel="manifest" href="/manifest.webmanifest" />
    <title>Card Scanner</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Write `frontend/public/manifest.webmanifest`**

```json
{
  "name": "Pokemon Card Scanner",
  "short_name": "Card Scan",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0b0d12",
  "theme_color": "#0b0d12",
  "icons": []
}
```

- [ ] **Step 7: Write the entry point and a placeholder App**

`frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`frontend/src/App.tsx`:

```tsx
export default function App() {
  return <main className="app"><h1>Card Scanner</h1></main>;
}
```

`frontend/src/styles.css`:

```css
:root {
  --bg: #0b0d12;
  --surface: #141821;
  --line: #242a38;
  --fg: #e8eaf0;
  --fg-dim: #98a0b3;
  --accent: #ffcb05;
  --ok: #3fb950;
  --warn: #d29922;
  color-scheme: dark;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}

.app {
  max-width: 560px;
  margin: 0 auto;
  padding: 16px;
  padding-bottom: max(16px, env(safe-area-inset-bottom));
}
```

- [ ] **Step 8: Install dependencies**

```bash
npm --prefix C:\ClaudeKnowledge\frontend install
```

- [ ] **Step 9: Verify HTTPS and the proxy actually work**

Start the backend in one terminal:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --port 8000
```

Start the frontend in another:

```bash
npm --prefix C:\ClaudeKnowledge\frontend run dev
```

Then verify three things and paste the evidence:

1. Vite prints an `https://` URL (not `http://`) for both Local and Network.
2. The proxy reaches the backend — with both running:
   ```bash
   curl -sk https://127.0.0.1:5173/api/health
   ```
   Expected: `{"status":"ok"}`. `-k` accepts the self-signed cert. **If this returns HTML instead
   of JSON, the proxy is misconfigured** and every later task will fail confusingly.
3. `https://127.0.0.1:5173` loads and shows "Card Scanner".

Stop both servers afterwards.

- [ ] **Step 10: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/public frontend/src && git commit -m "feat: scaffold pwa with https and api proxy"
```

Run `git status` first and confirm `node_modules/` is **not** staged.

---

## Task 5: API client and types

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/lib/format.ts`
- Test: `frontend/src/__tests__/client.test.ts`
- Test: `frontend/src/__tests__/format.test.ts`

- [ ] **Step 1: Write the failing tests**

`frontend/src/__tests__/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { formatMoney, formatStaleness, statusLabel } from "../lib/format";

describe("formatMoney", () => {
  it("formats a price", () => {
    expect(formatMoney(800.43)).toBe("$800.43");
  });

  it("renders an absent price as a dash rather than $0", () => {
    expect(formatMoney(null)).toBe("—");
  });

  it("keeps two decimals on whole numbers", () => {
    expect(formatMoney(12)).toBe("$12.00");
  });
});

describe("formatStaleness", () => {
  it("passes through a source date", () => {
    expect(formatStaleness("2026/07/29")).toBe("as of 2026/07/29");
  });

  it("says so when the source gave no date", () => {
    expect(formatStaleness("")).toBe("date unknown");
    expect(formatStaleness(null)).toBe("date unknown");
  });
});

describe("statusLabel", () => {
  it("maps each recognition status to human wording", () => {
    expect(statusLabel("confident")).toBe("Identified");
    expect(statusLabel("ambiguous")).toBe("Not sure — pick one");
    expect(statusLabel("not_found")).toBe("No card found");
  });
});
```

`frontend/src/__tests__/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmScan, correctScan, getResolvedPrice, recognize, refreshPrice } from "../api/client";

function mockFetch(status: number, body?: unknown) {
  const spy = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("recognize", () => {
  it("posts the blob to the proxied endpoint", async () => {
    const spy = mockFetch(200, { status: "confident", candidates: [] });

    await recognize(new Blob(["x"]), { rectify: true, variant: "normal" });

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/recognize");
    expect(url).toContain("rectify=true");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("throws with the status on failure", async () => {
    mockFetch(500);

    await expect(recognize(new Blob(["x"]), {})).rejects.toThrow(/500/);
  });
});

describe("getResolvedPrice", () => {
  it("returns null on 204 rather than throwing", async () => {
    mockFetch(204);

    expect(await getResolvedPrice("base1-4", "normal")).toBeNull();
  });

  it("returns the price on 200", async () => {
    mockFetch(200, { market: 800.43, source: "tcgplayer", source_updated_at: "2026/07/29" });

    const price = await getResolvedPrice("base1-4", "normal");

    expect(price?.market).toBe(800.43);
  });
});

describe("refreshPrice", () => {
  it("returns null when the source has nothing", async () => {
    mockFetch(204);

    expect(await refreshPrice("base1-58", "normal")).toBeNull();
  });
});

describe("scan feedback", () => {
  it("confirms a scan", async () => {
    const spy = mockFetch(200, { id: 1, confirmed: true });

    await confirmScan(1);

    expect(spy.mock.calls[0][0]).toContain("/api/scans/1/confirm");
  });

  it("sends the corrected card id", async () => {
    const spy = mockFetch(200, { id: 1, corrected_card_id: "base4-4" });

    await correctScan(1, "base4-4");

    expect(spy.mock.calls[0][0]).toContain("card_id=base4-4");
  });
});
```

- [ ] **Step 2: Run them, verify they fail**

```bash
npm --prefix C:\ClaudeKnowledge\frontend test
```

Expected: FAIL — cannot resolve `../api/client` or `../lib/format`.

- [ ] **Step 3: Write `frontend/src/api/types.ts`**

```ts
export type RecognitionStatus = "confident" | "ambiguous" | "not_found";

export interface Price {
  source: string;
  variant: string;
  low: number | null;
  mid: number | null;
  high: number | null;
  market: number | null;
  source_updated_at: string | null;
}

export interface CardSummary {
  id: string;
  name: string;
  number: string;
  rarity: string | null;
  set_id: string;
  set_name: string;
  image_small: string | null;
  image_large: string | null;
}

export interface Candidate {
  card_id: string;
  name: string;
  set_name: string;
  number: string;
  image_small: string | null;
  visual_score: number;
}

export interface RecognizeResponse {
  status: RecognitionStatus;
  confidence: number;
  visual_margin: number;
  card: CardSummary | null;
  price: Price | null;
  candidates: Candidate[];
  collector_number_read: string | null;
}

export interface Scan {
  id: number;
  status: string;
  predicted_card_id: string | null;
  corrected_card_id: string | null;
  confirmed: boolean;
  confidence: number | null;
  visual_margin: number | null;
  collector_number_read: string | null;
}
```

- [ ] **Step 4: Write `frontend/src/api/client.ts`**

```ts
import type { Price, RecognizeResponse, Scan } from "./types";

// Always relative: the Vite dev server proxies /api to the backend. Calling the
// backend's origin directly would be mixed content and blocked by the browser.
const BASE = "/api";

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

/** 204 means "no price", which is a normal state rather than an error. */
async function jsonOrNull<T>(response: Response): Promise<T | null> {
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function recognize(
  image: Blob,
  options: { rectify?: boolean; variant?: string },
): Promise<RecognizeResponse> {
  const params = new URLSearchParams({
    rectify: String(options.rectify ?? true),
    variant: options.variant ?? "normal",
  });
  const body = new FormData();
  body.append("file", image, "scan.jpg");

  return expectJson<RecognizeResponse>(
    await fetch(`${BASE}/recognize?${params}`, { method: "POST", body }),
  );
}

export async function getResolvedPrice(cardId: string, variant: string): Promise<Price | null> {
  const params = new URLSearchParams({ variant });
  return jsonOrNull<Price>(await fetch(`${BASE}/cards/${cardId}/price?${params}`));
}

export async function refreshPrice(cardId: string, variant: string): Promise<Price | null> {
  const params = new URLSearchParams({ variant });
  return jsonOrNull<Price>(
    await fetch(`${BASE}/cards/${cardId}/prices/refresh?${params}`, { method: "POST" }),
  );
}

export async function recordScan(
  image: Blob,
  result: RecognizeResponse,
): Promise<Scan> {
  const params = new URLSearchParams({ status: result.status });
  if (result.card) params.set("predicted_card_id", result.card.id);
  params.set("confidence", String(result.confidence));
  params.set("visual_margin", String(result.visual_margin));
  if (result.collector_number_read) {
    params.set("collector_number_read", result.collector_number_read);
  }
  const body = new FormData();
  body.append("file", image, "scan.jpg");

  return expectJson<Scan>(await fetch(`${BASE}/scans?${params}`, { method: "POST", body }));
}

export async function confirmScan(scanId: number): Promise<Scan> {
  return expectJson<Scan>(await fetch(`${BASE}/scans/${scanId}/confirm`, { method: "POST" }));
}

export async function correctScan(scanId: number, cardId: string): Promise<Scan> {
  const params = new URLSearchParams({ card_id: cardId });
  return expectJson<Scan>(
    await fetch(`${BASE}/scans/${scanId}/correct?${params}`, { method: "POST" }),
  );
}

export async function addToCollection(cardId: string, variant: string): Promise<void> {
  const response = await fetch(`${BASE}/collection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card_id: cardId, variant, quantity: 1 }),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
}
```

- [ ] **Step 5: Write `frontend/src/lib/format.ts`**

```ts
import type { RecognitionStatus } from "../api/types";

export function formatMoney(value: number | null | undefined): string {
  // An em dash, not $0.00 — an unpriced card is unknown, not worthless. The backend
  // is deliberately conservative about this and the UI must not undo that.
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

export function formatStaleness(sourceUpdatedAt: string | null | undefined): string {
  if (!sourceUpdatedAt) return "date unknown";
  return `as of ${sourceUpdatedAt}`;
}

export function statusLabel(status: RecognitionStatus): string {
  switch (status) {
    case "confident":
      return "Identified";
    case "ambiguous":
      return "Not sure — pick one";
    case "not_found":
      return "No card found";
  }
}
```

- [ ] **Step 6: Run the tests**

```bash
npm --prefix C:\ClaudeKnowledge\frontend test
```

Expected: 11 passed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api frontend/src/lib frontend/src/__tests__ && git commit -m "feat: add typed api client and display helpers"
```

---

## Task 6: Camera capture with framing guide

**Files:**
- Create: `frontend/src/components/CameraCapture.tsx`

Camera behaviour cannot be meaningfully unit-tested in jsdom — there is no camera. This task is
verified by hand on a real device, which is stated explicitly rather than faked with a mock.

- [ ] **Step 1: Write the component**

`frontend/src/components/CameraCapture.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  onCapture: (image: Blob) => void;
  busy: boolean;
}

// A real card is 2.5 x 3.5in. The guide matches that ratio so a card lined up inside
// it arrives at the server already close to the shape rectification expects.
const CARD_ASPECT = 2.5 / 3.5;

export default function CameraCapture({ onCapture, busy }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        // The overwhelmingly common cause is a non-secure context: getUserMedia is
        // simply absent over plain HTTP. Say so, rather than "camera unavailable".
        setError(
          window.isSecureContext
            ? "This browser has no camera API."
            : "Camera needs HTTPS. Open the https:// address, not http://.",
        );
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1920 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not open the camera.");
      }
    }

    void start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(blob);
      },
      "image/jpeg",
      0.92,
    );
  }, [onCapture]);

  if (error) {
    return (
      <div className="camera-error">
        <p>{error}</p>
        <p className="hint">
          You can still use the file picker below to upload a photo.
        </p>
      </div>
    );
  }

  return (
    <div className="camera">
      <div className="camera-frame">
        <video ref={videoRef} autoPlay playsInline muted />
        <div className="guide" style={{ aspectRatio: String(CARD_ASPECT) }} />
        <p className="guide-hint">Fill the box · dark background works best</p>
      </div>
      <button className="shutter" onClick={capture} disabled={busy}>
        {busy ? "Scanning…" : "Scan card"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Add the styles**

Append to `frontend/src/styles.css`:

```css
.camera-frame {
  position: relative;
  border-radius: 14px;
  overflow: hidden;
  background: #000;
  aspect-ratio: 3 / 4;
}

.camera-frame video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.guide {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  height: 78%;
  border: 2px solid var(--accent);
  border-radius: 10px;
  box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.45);
  pointer-events: none;
}

.guide-hint {
  position: absolute;
  bottom: 10px;
  left: 0;
  right: 0;
  text-align: center;
  margin: 0;
  font-size: 0.8rem;
  color: var(--fg-dim);
  text-shadow: 0 1px 3px #000;
}

.shutter {
  width: 100%;
  margin-top: 14px;
  padding: 15px;
  font-size: 1rem;
  font-weight: 600;
  border: none;
  border-radius: 12px;
  background: var(--accent);
  color: #1a1500;
}

.shutter:disabled { opacity: 0.55; }

.camera-error {
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}

.camera-error .hint { color: var(--fg-dim); font-size: 0.9rem; }
```

- [ ] **Step 3: Type-check**

```bash
npm --prefix C:\ClaudeKnowledge\frontend run build
```

Expected: builds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CameraCapture.tsx frontend/src/styles.css && git commit -m "feat: add camera capture with card framing guide"
```

---

## Task 7: Result display, candidate picker, and price line

**Files:**
- Create: `frontend/src/components/PriceLine.tsx`
- Create: `frontend/src/components/ScanResult.tsx`
- Create: `frontend/src/components/CandidatePicker.tsx`

- [ ] **Step 1: Write `frontend/src/components/PriceLine.tsx`**

The price loads separately from the card because an on-demand fetch takes 4.3 s on average and
9.1 s at worst. Blocking the card on it would make every first scan feel broken.

```tsx
import { useEffect, useState } from "react";

import { getResolvedPrice, refreshPrice } from "../api/client";
import type { Price } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

interface Props {
  cardId: string;
  variant: string;
  initial: Price | null;
}

type State = "idle" | "loading" | "fetching" | "none";

export default function PriceLine({ cardId, variant, initial }: Props) {
  const [price, setPrice] = useState<Price | null>(initial);
  const [state, setState] = useState<State>(initial ? "idle" : "loading");

  useEffect(() => {
    let cancelled = false;
    if (initial) return;

    async function load() {
      const cached = await getResolvedPrice(cardId, variant).catch(() => null);
      if (cancelled) return;
      if (cached) {
        setPrice(cached);
        setState("idle");
        return;
      }
      // Nothing cached: only 2 of 20,444 cards were priced at build time, so this is
      // the normal path. Go to the live source.
      setState("fetching");
      const fresh = await refreshPrice(cardId, variant).catch(() => null);
      if (cancelled) return;
      setPrice(fresh);
      setState(fresh ? "idle" : "none");
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [cardId, variant, initial]);

  if (state === "loading") return <p className="price muted">Checking price…</p>;
  if (state === "fetching") return <p className="price muted">Fetching live price…</p>;
  if (!price) return <p className="price muted">No price available</p>;

  return (
    <p className="price">
      <strong>{formatMoney(price.market)}</strong>
      <span className="price-meta">
        {price.source} · {formatStaleness(price.source_updated_at)}
      </span>
    </p>
  );
}
```

- [ ] **Step 2: Write `frontend/src/components/CandidatePicker.tsx`**

```tsx
import type { Candidate } from "../api/types";

interface Props {
  candidates: Candidate[];
  onPick: (cardId: string) => void;
  onReject: () => void;
}

export default function CandidatePicker({ candidates, onPick, onReject }: Props) {
  return (
    <div className="picker">
      <ul className="candidates">
        {candidates.map((candidate) => (
          <li key={candidate.card_id}>
            <button onClick={() => onPick(candidate.card_id)}>
              {candidate.image_small && <img src={candidate.image_small} alt="" loading="lazy" />}
              <span className="candidate-text">
                <strong>{candidate.name}</strong>
                <span className="candidate-meta">
                  {candidate.set_name} · #{candidate.number}
                </span>
              </span>
              <span className="score">{(candidate.visual_score * 100).toFixed(0)}%</span>
            </button>
          </li>
        ))}
      </ul>
      <button className="reject" onClick={onReject}>
        None of these
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Write `frontend/src/components/ScanResult.tsx`**

```tsx
import type { RecognizeResponse } from "../api/types";
import { statusLabel } from "../lib/format";
import CandidatePicker from "./CandidatePicker";
import PriceLine from "./PriceLine";

interface Props {
  result: RecognizeResponse;
  variant: string;
  onConfirm: () => void;
  onPick: (cardId: string) => void;
  onReject: () => void;
  onRescan: () => void;
}

export default function ScanResult({
  result,
  variant,
  onConfirm,
  onPick,
  onReject,
  onRescan,
}: Props) {
  const { card, status } = result;

  return (
    <section className="result">
      <header className={`result-status ${status}`}>
        <span>{statusLabel(status)}</span>
        <span className="confidence">{(result.confidence * 100).toFixed(0)}%</span>
      </header>

      {card && (
        <div className="card-detail">
          {card.image_small && <img src={card.image_small} alt={card.name} />}
          <div>
            <h2>{card.name}</h2>
            <p className="card-meta">
              {card.set_name} · #{card.number}
              {card.rarity ? ` · ${card.rarity}` : ""}
            </p>
            <PriceLine cardId={card.id} variant={variant} initial={result.price} />
          </div>
        </div>
      )}

      {result.collector_number_read && (
        <p className="ocr-note">Read card number: {result.collector_number_read}</p>
      )}

      {status === "confident" && (
        <div className="actions">
          <button className="primary" onClick={onConfirm}>
            Correct — add to collection
          </button>
          <button onClick={onReject}>Wrong card</button>
        </div>
      )}

      {status === "ambiguous" && (
        <CandidatePicker candidates={result.candidates} onPick={onPick} onReject={onReject} />
      )}

      {status === "not_found" && (
        <p className="muted">
          No card detected. Try a darker background, and leave a margin around the card.
        </p>
      )}

      <button className="rescan" onClick={onRescan}>
        Scan another
      </button>
    </section>
  );
}
```

- [ ] **Step 4: Add the styles**

Append to `frontend/src/styles.css`:

```css
.result { margin-top: 18px; }

.result-status {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 10px 10px 0 0;
  font-weight: 600;
  background: var(--surface);
  border: 1px solid var(--line);
  border-bottom: none;
}

.result-status.confident { color: var(--ok); }
.result-status.ambiguous { color: var(--warn); }
.result-status.not_found { color: var(--fg-dim); }
.confidence { color: var(--fg-dim); font-weight: 400; }

.card-detail {
  display: flex;
  gap: 14px;
  padding: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
}

.card-detail img { width: 96px; border-radius: 6px; }
.card-detail h2 { margin: 0 0 4px; font-size: 1.1rem; }
.card-meta { margin: 0 0 10px; color: var(--fg-dim); font-size: 0.88rem; }

.price { margin: 0; font-size: 1.35rem; }
.price.muted { font-size: 0.9rem; color: var(--fg-dim); }
.price-meta { display: block; font-size: 0.78rem; color: var(--fg-dim); font-weight: 400; }

.ocr-note {
  margin: 0;
  padding: 8px 14px;
  font-size: 0.8rem;
  color: var(--fg-dim);
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: none;
}

.actions { display: flex; gap: 8px; margin-top: 12px; }
.actions button, .reject, .rescan {
  flex: 1;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--fg);
  font-size: 0.95rem;
}
.actions .primary { background: var(--ok); color: #04210c; border-color: transparent; font-weight: 600; }

.candidates { list-style: none; margin: 12px 0 8px; padding: 0; display: grid; gap: 8px; }
.candidates button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--fg);
}
.candidates img { width: 44px; border-radius: 4px; }
.candidate-text { flex: 1; display: flex; flex-direction: column; }
.candidate-meta { font-size: 0.8rem; color: var(--fg-dim); }
.score { color: var(--fg-dim); font-size: 0.85rem; }

.reject, .rescan { width: 100%; margin-top: 8px; }
.muted { color: var(--fg-dim); }
```

- [ ] **Step 5: Type-check**

```bash
npm --prefix C:\ClaudeKnowledge\frontend run build
```

Expected: builds cleanly.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components frontend/src/styles.css && git commit -m "feat: add scan result, candidate picker, and async price line"
```

---

## Task 8: Wire the app together

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the app shell**

```tsx
import { useCallback, useState } from "react";

import {
  addToCollection,
  confirmScan,
  correctScan,
  recognize,
  recordScan,
} from "./api/client";
import type { RecognizeResponse } from "./api/types";
import CameraCapture from "./components/CameraCapture";
import ScanResult from "./components/ScanResult";

const VARIANT = "normal";

export default function App() {
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const handleCapture = useCallback(async (image: Blob) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const response = await recognize(image, { rectify: true, variant: VARIANT });
      setResult(response);
      // Log every scan, including failures — the not_found cases are the ones worth
      // studying, and this is the project's only source of real-photo ground truth.
      const scan = await recordScan(image, response).catch(() => null);
      setScanId(scan?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  const handleConfirm = useCallback(async () => {
    if (result?.card) {
      await addToCollection(result.card.id, VARIANT).catch(() => null);
      setNote(`Added ${result.card.name} to your collection.`);
    }
    if (scanId !== null) await confirmScan(scanId).catch(() => null);
  }, [result, scanId]);

  const handlePick = useCallback(
    async (cardId: string) => {
      await addToCollection(cardId, VARIANT).catch(() => null);
      if (scanId !== null) await correctScan(scanId, cardId).catch(() => null);
      setNote("Thanks — that correction helps the next scan.");
    },
    [scanId],
  );

  const handleReject = useCallback(() => {
    setNote("Marked as wrong. Scan it again, or try a darker background.");
  }, []);

  const handleRescan = useCallback(() => {
    setResult(null);
    setScanId(null);
    setNote(null);
    setError(null);
  }, []);

  return (
    <main className="app">
      <h1>Card Scanner</h1>

      {!result && <CameraCapture onCapture={handleCapture} busy={busy} />}

      {error && <p className="error">{error}</p>}
      {note && <p className="note">{note}</p>}

      {result && (
        <ScanResult
          result={result}
          variant={VARIANT}
          onConfirm={handleConfirm}
          onPick={handlePick}
          onReject={handleReject}
          onRescan={handleRescan}
        />
      )}
    </main>
  );
}
```

- [ ] **Step 2: Add the styles**

Append to `frontend/src/styles.css`:

```css
h1 { font-size: 1.25rem; margin: 4px 0 16px; }

.error, .note {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.9rem;
}
.error { background: #3a1418; color: #ffb4ab; }
.note { background: var(--surface); color: var(--fg-dim); border: 1px solid var(--line); }
```

- [ ] **Step 3: Build and run the full check**

```bash
npm --prefix C:\ClaudeKnowledge\frontend run build
```

Then:

```bash
npm --prefix C:\ClaudeKnowledge\frontend test
```

Expected: build clean, 11 tests passing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css && git commit -m "feat: wire capture, recognition, feedback, and collection together"
```

---

## Task 9: End-to-end verification on a desktop browser

No new files. This proves the whole chain works before a phone is involved.

- [ ] **Step 1: Start both servers**

Backend:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --port 8000
```

Frontend:

```bash
npm --prefix C:\ClaudeKnowledge\frontend run dev
```

- [ ] **Step 2: Verify the proxy chain**

```bash
curl -sk https://127.0.0.1:5173/api/health
```

Expected: `{"status":"ok"}`.

- [ ] **Step 3: Drive a real scan through the API the app uses**

Download a reference card and post it through the proxy exactly as the app does:

```bash
curl -sk -o /tmp/card.png https://images.pokemontcg.io/base1/4_hires.png && curl -sk -X POST "https://127.0.0.1:5173/api/recognize?rectify=false&variant=holofoil" -F "file=@/tmp/card.png"
```

Expected: JSON with `"status": "confident"` and Charizard. Paste it.

- [ ] **Step 4: Verify on-demand pricing works through the proxy**

Pick a card that had no price, and confirm the refresh endpoint populates one:

```bash
curl -sk -X POST "https://127.0.0.1:5173/api/cards/base1-60/prices/refresh?variant=normal"
```

Expected: either a price JSON body, or HTTP 204 if the upstream had nothing. Report which, and how
long it took. Both are valid; a 500 is not.

- [ ] **Step 5: Verify scan logging round-trips**

```bash
curl -sk "https://127.0.0.1:5173/api/scans/accuracy"
```

Expected: `{"reviewed":0,"correct":0,"top1_accuracy":0.0}` on a fresh database.

- [ ] **Step 6: Open the app in a desktop browser**

Load `https://127.0.0.1:5173`, accept the certificate warning. The camera will prompt for
permission — a laptop webcam is fine for proving the capture path works even if it cannot resolve a
card. Confirm: video appears, the yellow guide is centred, and pressing "Scan card" produces a
result panel rather than a silent failure.

**Report what actually happened, including if recognition failed** — a webcam photo of a screen is a
hard input and a `not_found` here is informative, not a bug.

- [ ] **Step 7: Stop both servers and commit nothing**

This task changes no files. If you found a defect, report it rather than fixing it silently.

---

## Task 10: Collect real photos and measure

**This task requires Lucas and cannot be completed by an agent.** Its purpose is to produce the one
number the project still does not have.

- [ ] **Step 1: Prepare the phone session**

Both servers running, frontend bound to the LAN (`npm run dev` already passes `--host`). Note the
`https://<lan-ip>:5173` address Vite prints.

- [ ] **Step 2: Hand over to Lucas with these instructions**

> Open `https://<lan-ip>:5173` on your phone and accept the certificate warning (it is self-signed;
> that warning is expected and is the price of the camera working at all).
>
> Scan **30–50 real cards**. Deliberately vary them: different eras (vintage Base Set through modern
> Scarlet & Violet), holo and non-holo, different lighting, and a few deliberately awkward shots.
>
> For every scan, tap either **"Correct — add to collection"** or, if it got it wrong, pick the right
> card from the list. That tap is the label — a scan nobody reviews teaches us nothing.

- [ ] **Step 3: Measure**

```bash
curl -sk "https://127.0.0.1:5173/api/scans/accuracy"
```

Record `reviewed`, `correct`, and `top1_accuracy`. **This is the honest accuracy number for the
project.** Compare it against the 99.8% clean / 85.4% stacked-degradation figures measured on
reference images in Phase 1a, and state the gap plainly.

- [ ] **Step 4: Study the failures**

```bash
curl -sk "https://127.0.0.1:5173/api/scans?limit=100"
```

For every scan with a `corrected_card_id`, the saved image is under `data/scans/`. Look at them and
characterise the failure modes: is it rectification picking the wrong quad, OCR misreading, glare on
holos, or genuine visual confusion between similar cards? Group them and report counts.

The answer determines what Phase 1c should be. Do not guess it in advance.

---

## Task 11: Record results and merge

**Files:**
- Modify: `PROJECT.md`, `docs/index.html`, `CLAUDE.md`

- [ ] **Step 1: Record the real-photo accuracy in `PROJECT.md`**

Add a "Phase 1b — shipped" section with the **measured** real-photo top-1 accuracy from Task 10, the
sample size, and the failure-mode breakdown. Use the real numbers, not the reference-image ones.

State the comparison explicitly: reference images gave 99.8% clean / 85.4% stacked; real photos gave
X%. That gap is the single most useful fact the project has learned.

- [ ] **Step 2: Update the roadmap**

In `PROJECT.md`, mark Phase 1b complete. In `docs/index.html`, change the Phase 01b chip from
`<span class="st now">Next</span>` to `<span class="st done">Complete</span>` and update the header
tag to mention the real-photo accuracy.

- [ ] **Step 3: Add the frontend commands to `CLAUDE.md`**

Under `## Commands`:

```
- Frontend dev server: `npm --prefix C:\ClaudeKnowledge\frontend run dev` (HTTPS on :5173, proxies /api to :8000)
- Frontend tests: `npm --prefix C:\ClaudeKnowledge\frontend test`
```

Under `## Conventions`:

```
- **The camera requires HTTPS.** `getUserMedia` is absent over plain HTTP, so the dev server uses a self-signed cert. An HTTPS page also cannot call the HTTP backend directly — that is mixed content, so all frontend requests go through Vite's `/api` proxy, never to the backend origin.
- **Never block a scan on a price fetch.** On-demand pricing measured 4.3s mean and 9.1s worst case; the card renders immediately and the price line loads on its own.
- **Log every scan, including failures.** `not_found` and corrected scans are the project's only real-world labelled data.
```

Under `## Project structure`, add `frontend/` — the React PWA.

- [ ] **Step 4: Merge and push**

```bash
git checkout main && git merge --no-ff phase-1b-scan-pwa && git push origin main
```

---

## Definition of done

- [ ] `pytest` passes (roughly 179 backend tests).
- [ ] `npm --prefix frontend test` passes (11 tests) and `npm run build` is clean.
- [ ] `curl -sk https://127.0.0.1:5173/api/health` returns `{"status":"ok"}` — the HTTPS + proxy chain works.
- [ ] The app loads on a phone over HTTPS and the camera opens.
- [ ] A recognized card shows a price, fetched on demand if it was not cached.
- [ ] An ambiguous result offers ranked candidates and records the pick.
- [ ] **`/scans/accuracy` reports a real number over at least 30 reviewed real-card scans.**
- [ ] `node_modules/`, `data/scans/`, and the FAISS index are all uncommitted.

## What this phase is really for

Everything before it was measured on degraded reference images. Task 10 replaces that with
photographs of physical cards, and the resulting number decides what comes next: if accuracy holds,
the roadmap continues to Phase 2. If it drops sharply, the failure-mode breakdown from Task 10 Step 4
says whether the fix is better rectification, better OCR, or fine-tuning the encoder on the very
scan images this phase started collecting.
