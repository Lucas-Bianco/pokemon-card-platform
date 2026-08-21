# Phase 06 — Set-Completion Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only set-completion optimizer — per-set checklist (owned/missing) with an honest estimated cost to complete, via `PriceService.latest_price`. No new tables, no migrations.

**Architecture:** A `CompletionService` (`catalog/completion.py`) joins the catalog (cards + sets) to the collection and resolves missing-card prices through the sacred `PriceService.latest_price` path. Two read-only routes (`GET /sets`, `GET /sets/{set_id}`). A 10th **Sets** frontend tab (`Sets.tsx`) + a `SetDetail.tsx` overlay (AppShell `selectedSet` state, mirroring `selectedCard`). All honest empty states — 0% not fabricated, `—` / "no market price" not `$0`.

**Tech Stack:** Python 3.12 via `backend/.venv`, FastAPI + Pydantic v2 + SQLAlchemy 2 (sqlite), pytest. Vite + React 19 + TypeScript strict + vitest (jsdom, `container.*` house style, NO jest-dom).

**Spec:** `docs/superpowers/specs/2026-08-21-set-completion-design.md` (read it first).

**Do-not-break contract (re-read before T7/T8):** the 10th tab is named **"Sets"** (never "Scan"), so `getByRole("button", { name: "Scan" })` still resolves to one element. All new CSS classes are distinct (`.sets-*`, `.set-detail-*`, `.checklist-*`); no existing rule renamed/removed. The `.bottom-nav` `overflow-x: auto` change is visual-only. No frozen string touched. **Sacred constraints:** `PriceService.latest_price` only (never ad-hoc); staleness surfaced (`source` + `source_updated_at`, `""` sentinel → `None` on the wire); `func.lower().like()` not `ilike`; honest empty states; read-only (no new tables/migrations/snapshots/`data/` writes).

---

## File Structure

- **Create:** `backend/src/cardplatform/catalog/completion.py` — `CompletionService` + `SetProgress`/`SetCompletion`/`ChecklistEntry`/`CompletionSummary` dataclasses + `_number_sort_key`.
- **Create:** `backend/src/cardplatform/catalog/api_models.py` — Pydantic v2 wire models (`from_attributes=True`).
- **Modify:** `backend/src/cardplatform/api.py` — `GET /sets`, `GET /sets/{set_id}`, `_require_set` helper, imports.
- **Create:** `backend/tests/test_completion.py` — service unit tests.
- **Create:** `backend/tests/test_completion_api.py` — route tests.
- **Modify:** `frontend/src/api/types.ts` — `SetProgress`, `SetCompletion`, `ChecklistEntry`, `CompletionSummary`.
- **Modify:** `frontend/src/api/client.ts` — `getSets`, `getSetCompletion`.
- **Create:** `frontend/src/components/Sets.tsx` — 10th tab (searchable set list + progress bars).
- **Create:** `frontend/src/components/SetDetail.tsx` — overlay (summary KPIs + checklist grid).
- **Create:** `frontend/src/__tests__/Sets.test.tsx`
- **Create:** `frontend/src/__tests__/SetDetail.test.tsx`
- **Modify:** `frontend/src/components/AppShell.tsx` — `TabView` + `"sets"`, `selectedSet` state, `SetsGlyph`, tab wiring (both navs), command-palette nav command, `<AnimatePresence>` SetDetail branch.
- **Modify:** `frontend/src/styles.css` — additive `.sets-*`, `.set-detail-*`, `.checklist-*`, `.bottom-nav` overflow.
- **Modify:** `AI_CONTEXT.md`, `PROJECT.md`, memory + `MEMORY.md` (T9).

---

### Task 1: CompletionService + unit tests

**Files:**
- Create: `backend/src/cardplatform/catalog/completion.py`
- Test: `backend/tests/test_completion.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_completion.py`:
```python
from __future__ import annotations

import pytest

from cardplatform.catalog.completion import CompletionService
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot
from cardplatform.prices.service import PriceService


@pytest.fixture
def seeded(db):
    # Two sets. base1 has plain numeric numbers + a suffixed promo. promo1 has a
    # non-numeric prefix (TG01) that must sort after the plain numerics.
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09", total=3))
    db.add(CardSet(id="promo1", name="Promo", series="Promo", release_date="2020/01/01", total=1))
    db.add(Card(id="base1-1", set_id="base1", name="Bulbasaur", number="1", rarity="Common"))
    db.add(Card(id="base1-10", set_id="base1", name="Pikachu", number="10", rarity="Common"))
    db.add(Card(id="base1-4a", set_id="base1", name="Snap Promo", number="4a", rarity="Promo"))
    db.add(Card(id="promo1-1", set_id="promo1", name="Mew Promo", number="TG01", rarity="Promo"))
    db.commit()
    return db


def snap(db, card_id, market, source="tcgplayer", variant="normal", stamp="2026/07/28"):
    db.add(
        PriceSnapshot(
            card_id=card_id, source=source, variant=variant, market=market, source_updated_at=stamp
        )
    )
    db.commit()


@pytest.fixture
def service(seeded):
    return CompletionService(seeded, PriceService(seeded))


def test_list_sets_orders_by_release_date_desc_and_counts_owned(service, seeded):
    # Own one card in base1 (any variant counts as owned).
    seeded.add(CollectionItem(card_id="base1-10", variant="holofoil", quantity=1))
    seeded.commit()
    sets = service.list_sets()
    assert [s.id for s in sets] == ["promo1", "base1"]  # newer first
    base1 = next(s for s in sets if s.id == "base1")
    assert base1.checklist_size == 3
    assert base1.owned == 1
    assert base1.pct_complete == pytest.approx(1 / 3)
    promo = next(s for s in sets if s.id == "promo1")
    assert promo.owned == 0
    assert promo.pct_complete == 0  # honest 0%, never fabricated


def test_list_sets_filter_uses_lower_like_not_ilike(service):
    sets = service.list_sets(query="base")
    assert [s.id for s in sets] == ["base1"]
    # Accented names: func.lower().like() matches; this just confirms the path.
    assert service.list_sets(query="PROMO")[0].id == "promo1"


def test_list_sets_zero_cards_does_not_divide_by_zero(db):
    db.add(CardSet(id="empty", name="Empty", series="X", release_date="2024/01/01"))
    db.commit()
    svc = CompletionService(db, PriceService(db))
    s = svc.list_sets()[0]
    assert s.checklist_size == 0
    assert s.pct_complete == 0


def test_set_detail_natural_sort_numeric_then_suffix_then_prefix(service):
    detail = service.set_detail("base1")
    numbers = [c.number for c in detail.cards]
    # 1, then 4a (suffix of 4, sorts right after plain numerics < 10), then 10.
    # TG01 lives in promo1, not here.
    assert numbers == ["1", "4a", "10"]


def test_set_detail_owned_flags_and_missing_prices(service, seeded):
    snap(seeded, "base1-1", market=2.0)  # priced missing
    seeded.add(CollectionItem(card_id="base1-10", variant="normal", quantity=1))
    seeded.commit()
    detail = service.set_detail("base1")
    by_id = {c.card_id: c for c in detail.cards}
    assert by_id["base1-10"].owned is True          # owned
    assert by_id["base1-10"].market is None         # owned cards are not priced
    assert by_id["base1-1"].owned is False
    assert by_id["base1-1"].market == 2.0           # via latest_price
    assert by_id["base1-1"].source == "tcgplayer"
    assert by_id["base1-1"].source_updated_at == "2026/07/28"
    assert by_id["base1-4a"].owned is False
    assert by_id["base1-4a"].market is None          # unpriced missing


def test_set_detail_summary_honest_costs(service, seeded):
    snap(seeded, "base1-1", market=2.0)
    snap(seeded, "base1-10", market=5.0)
    seeded.commit()
    detail = service.set_detail("base1")  # own nothing -> 3 missing, 2 priced
    s = detail.summary
    assert s.owned == 0
    assert s.checklist_size == 3
    assert s.missing == 3
    assert s.pct_complete == 0
    assert s.est_cost_to_complete == 7.0     # 2.0 + 5.0
    assert s.unpriced_missing == 1           # base1-4a


def test_set_detail_summary_none_when_all_missing_unpriced(service):
    detail = service.set_detail("base1")  # no snapshots at all
    s = detail.summary
    assert s.est_cost_to_complete is None  # never 0.0 when nothing is priced
    assert s.unpriced_missing == 3


def test_set_detail_summary_zero_when_complete(service, seeded):
    for cid in ("base1-1", "base1-10", "base1-4a"):
        seeded.add(CollectionItem(card_id=cid, variant="normal", quantity=1))
    seeded.commit()
    s = service.set_detail("base1").summary
    assert s.missing == 0
    assert s.est_cost_to_complete == 0.0   # complete -> $0 to finish is honest
    assert s.unpriced_missing == 0


def test_set_detail_unknown_set_raises(service):
    with pytest.raises(LookupError):
        service.set_detail("nope")


def test_latest_price_empty_string_stamp_becomes_none_on_wire(service, seeded):
    snap(seeded, "base1-1", market=2.0, stamp="")  # "" sentinel
    seeded.commit()
    detail = service.set_detail("base1")
    entry = next(c for c in detail.cards if c.card_id == "base1-1")
    assert entry.source_updated_at is None  # "" -> None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_completion.py -q`
Expected: FAIL — `ImportError: cannot import name 'CompletionService'`.

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/catalog/completion.py`:
```python
"""Set-completion optimizer: per-set owned/missing checklist + honest cost to complete.

Read-only. Missing-card prices come through ``PriceService.latest_price`` — the sacred
price path, never ad-hoc. Owned cards are not priced here (they are already acquired);
pricing them is a deferred follow-up. No tables, no snapshots, no ``data/`` writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CardSet, CollectionItem
from cardplatform.prices.service import PriceService

# Natural collector-number sort. Plain numerics first ("1","2","10"); a numeric base
# with a suffix ("4a") sorts right after its base; a non-numeric prefix ("TG01","SV01")
# sorts after every plain numeric (promos/secret rares at the end of the checklist).
_NUM_RE = re.compile(r"^(\d+)(.*)$")
_SENTINEL = 10**9


def _number_sort_key(number: str | None) -> tuple[int, str]:
    m = _NUM_RE.match(number or "")
    if not m:
        return (_SENTINEL, number or "")
    return (int(m.group(1)), m.group(2))


@dataclass(frozen=True)
class SetProgress:
    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    owned: int
    checklist_size: int
    pct_complete: float


@dataclass(frozen=True)
class ChecklistEntry:
    card_id: str
    name: str
    number: str
    rarity: str | None
    image_small: str | None
    owned: bool
    market: float | None
    source: str | None
    source_updated_at: str | None


@dataclass(frozen=True)
class CompletionSummary:
    owned: int
    checklist_size: int
    missing: int
    pct_complete: float
    est_cost_to_complete: float | None
    unpriced_missing: int


@dataclass(frozen=True)
class SetCompletion:
    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    cards: list[ChecklistEntry]
    summary: CompletionSummary


class CompletionService:
    def __init__(self, session: Session, price_service: PriceService) -> None:
        self.session = session
        self.price_service = price_service

    def list_sets(self, query: str | None = None) -> list[SetProgress]:
        stmt = select(CardSet)
        if query:
            # lower() not ilike(): SQLite LIKE is ASCII-only case-insensitive; the
            # catalog carries accented names. Sacred constraint.
            stmt = stmt.where(func.lower(CardSet.name).like(f"%{query.lower()}%"))
        stmt = stmt.order_by(CardSet.release_date.desc(), CardSet.name)
        sets = list(self.session.scalars(stmt).all())

        owned_counts = dict(
            self.session.execute(
                select(Card.set_id, func.count(func.distinct(CollectionItem.card_id)))
                .join(CollectionItem, CollectionItem.card_id == Card.id)
                .group_by(Card.set_id)
            ).all()
        )
        checklist_counts = dict(
            self.session.execute(
                select(Card.set_id, func.count()).group_by(Card.set_id)
            ).all()
        )

        out: list[SetProgress] = []
        for s in sets:
            size = checklist_counts.get(s.id, 0)
            owned = owned_counts.get(s.id, 0)
            out.append(
                SetProgress(
                    id=s.id,
                    name=s.name,
                    series=s.series,
                    release_date=s.release_date,
                    total=s.total,
                    printed_total=s.printed_total,
                    owned=owned,
                    checklist_size=size,
                    pct_complete=(owned / size) if size else 0,
                )
            )
        return out

    def set_detail(self, set_id: str) -> SetCompletion:
        s = self.session.get(CardSet, set_id)
        if s is None:
            raise LookupError(f"unknown set: {set_id!r}")

        cards = list(
            self.session.scalars(select(Card).where(Card.set_id == set_id)).all()
        )
        owned_ids = set(
            self.session.scalars(
                select(CollectionItem.card_id)
                .join(Card, Card.id == CollectionItem.card_id)
                .where(Card.set_id == set_id)
            ).all()
        )

        entries: list[ChecklistEntry] = []
        for c in sorted(cards, key=lambda card: _number_sort_key(card.number)):
            owned = c.id in owned_ids
            market: float | None = None
            source: str | None = None
            source_updated_at: str | None = None
            if not owned:
                snap = self.price_service.latest_price(c.id, "normal")
                if snap is not None:
                    market = snap.market
                    source = snap.source
                    # "" sentinel (no source timestamp) -> None on the wire.
                    source_updated_at = snap.source_updated_at or None
            entries.append(
                ChecklistEntry(
                    card_id=c.id,
                    name=c.name,
                    number=c.number,
                    rarity=c.rarity,
                    image_small=c.image_small,
                    owned=owned,
                    market=market,
                    source=source,
                    source_updated_at=source_updated_at,
                )
            )

        owned = len(owned_ids)
        checklist_size = len(cards)
        missing = checklist_size - owned
        missing_entries = [e for e in entries if not e.owned]
        priced_missing = [e for e in missing_entries if e.market is not None]
        if missing == 0:
            est_cost: float | None = 0.0
        elif priced_missing:
            est_cost = sum(e.market for e in priced_missing)
        else:
            est_cost = None
        unpriced_missing = len(missing_entries) - len(priced_missing)

        summary = CompletionSummary(
            owned=owned,
            checklist_size=checklist_size,
            missing=missing,
            pct_complete=(owned / checklist_size) if checklist_size else 0,
            est_cost_to_complete=est_cost,
            unpriced_missing=unpriced_missing,
        )
        return SetCompletion(
            id=s.id,
            name=s.name,
            series=s.series,
            release_date=s.release_date,
            total=s.total,
            printed_total=s.printed_total,
            cards=entries,
            summary=summary,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_completion.py -q`
Expected: PASS — 10 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/catalog/completion.py backend/tests/test_completion.py
git commit -m "feat(catalog): CompletionService — set checklist + honest cost to complete"
```

---

### Task 2: Pydantic wire models

**Files:**
- Create: `backend/src/cardplatform/catalog/api_models.py`

- [ ] **Step 1: Write the models**

`backend/src/cardplatform/catalog/api_models.py`:
```python
"""Pydantic wire models for the set-completion API (Phase 06).

Mirrors the sealed/deals api_models idiom: Pydantic v2 with
``ConfigDict(from_attributes=True)`` so the service's frozen dataclasses serialise
directly. Every nullable field surfaces as None — an unpriced missing card is never a
fabricated $0.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SetProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    owned: int
    checklist_size: int
    pct_complete: float


class ChecklistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    card_id: str
    name: str
    number: str
    rarity: str | None
    image_small: str | None
    owned: bool
    market: float | None
    source: str | None
    source_updated_at: str | None


class CompletionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owned: int
    checklist_size: int
    missing: int
    pct_complete: float
    est_cost_to_complete: float | None
    unpriced_missing: int


class SetCompletionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    series: str | None
    release_date: str | None
    total: int | None
    printed_total: int | None
    cards: list[ChecklistEntryOut]
    summary: CompletionSummaryOut
```

- [ ] **Step 2: Sanity-check the import**

Run: `backend/.venv/Scripts/python -c "from cardplatform.catalog.api_models import SetProgressOut, SetCompletionOut; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/cardplatform/catalog/api_models.py
git commit -m "feat(catalog): set-completion Pydantic wire models"
```

---

### Task 3: API routes + route tests

**Files:**
- Modify: `backend/src/cardplatform/api.py` (imports + `_require_set` + two routes)
- Test: `backend/tests/test_completion_api.py`

- [ ] **Step 1: Write the failing route tests**

`backend/tests/test_completion_api.py`:
```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app
from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


@pytest.fixture
def client(database):
    app = create_app(database=database)
    return TestClient(app)


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09", total=2))
    db.add(Card(id="base1-1", set_id="base1", name="Bulbasaur", number="1"))
    db.add(Card(id="base1-2", set_id="base1", name="Ivysaur", number="2"))
    db.add(CollectionItem(card_id="base1-1", variant="normal", quantity=1))
    db.add(PriceSnapshot(card_id="base1-2", source="tcgplayer", variant="normal",
                         market=3.0, source_updated_at="2026/07/28"))
    db.commit()


def test_get_sets_returns_progress(client, seeded):
    r = client.get("/sets")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == "base1"
    assert body[0]["owned"] == 1
    assert body[0]["checklist_size"] == 2
    assert body[0]["pct_complete"] == 0.5


def test_get_sets_q_filter(client, seeded):
    r = client.get("/sets?q=bas")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == ["base1"]


def test_get_sets_whitespace_q_is_422(client):
    r = client.get("/sets?q=%20%20")  # whitespace-only
    assert r.status_code == 422


def test_get_sets_limit_out_of_range_is_422(client):
    r = client.get("/sets?limit=0")
    assert r.status_code == 422
    r2 = client.get("/sets?limit=201")
    assert r2.status_code == 422


def test_get_set_detail(client, seeded):
    r = client.get("/sets/base1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "base1"
    by_id = {c["card_id"]: c for c in body["cards"]}
    assert by_id["base1-1"]["owned"] is True
    assert by_id["base1-2"]["owned"] is False
    assert by_id["base1-2"]["market"] == 3.0
    assert body["summary"]["owned"] == 1
    assert body["summary"]["missing"] == 1
    assert body["summary"]["est_cost_to_complete"] == 3.0
    assert body["summary"]["unpriced_missing"] == 0


def test_get_set_detail_unknown_is_404(client):
    r = client.get("/sets/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_completion_api.py -q`
Expected: FAIL — routes do not exist (404/422 mismatches).

- [ ] **Step 3: Add the routes to `api.py`**

Add to the imports near the other api_models imports:
```python
from cardplatform.catalog.api_models import (
    ChecklistEntryOut,
    CompletionSummaryOut,
    SetCompletionOut,
    SetProgressOut,
)
from cardplatform.catalog.completion import CompletionService
```
Add `PriceService` to the prices import if not already imported (it is used by other routes; check `from cardplatform.prices.service import PriceService` — add if missing).

Add the routes (place near the `/cards` search route, after `search_cards`):
```python
    @app.get("/sets", response_model=list[SetProgressOut])
    def list_sets(
        q: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> list[SetProgressOut]:
        # q is optional; when present, min_length=1 rejects empty after strip via the
        # whitespace path below. FastAPI's min_length counts whitespace, so a
        # whitespace-only q already 422s here (matches the sealed-deals contract).
        service = CompletionService(session, PriceService(session))
        sets = service.list_sets(query=q)
        return [SetProgressOut.model_validate(s) for s in sets[:limit]]

    @app.get("/sets/{set_id}", response_model=SetCompletionOut)
    def get_set(set_id: str, session: Session = Depends(get_session)) -> SetCompletionOut:
        service = CompletionService(session, PriceService(session))
        try:
            detail = service.set_detail(set_id)
        except LookupError:
            raise HTTPException(status_code=404, detail=f"unknown set: {set_id!r}")
        return SetCompletionOut.model_validate(detail)
```

> **Note on the whitespace 422:** FastAPI's `Query(min_length=1)` counts the raw string length, so `"  "` (length 2) passes the min_length gate. To match the spec's "whitespace-only re-raises 422" contract, add an explicit guard inside `list_sets` before constructing the service:
> ```python
>     if q is not None and not q.strip():
>         raise HTTPException(status_code=422, detail="q must not be blank")
> ```
> Place it as the first line of the function body.

- [ ] **Step 4: Run the route tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_completion_api.py -q`
Expected: PASS — 6 tests.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS — prior 568 + 16 new = 584.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/api.py backend/tests/test_completion_api.py
git commit -m "feat(api): GET /sets + GET /sets/{id} — set completion routes"
```

---

### Task 4: Frontend types + API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add the types**

Append to `frontend/src/api/types.ts`:
```ts
export interface SetProgress {
  id: string;
  name: string;
  series: string | null;
  release_date: string | null;
  total: number | null;
  printed_total: number | null;
  owned: number;
  checklist_size: number;
  pct_complete: number;
}

export interface ChecklistEntry {
  card_id: string;
  name: string;
  number: string;
  rarity: string | null;
  image_small: string | null;
  owned: boolean;
  market: number | null;
  source: string | null;
  source_updated_at: string | null;
}

export interface CompletionSummary {
  owned: number;
  checklist_size: number;
  missing: number;
  pct_complete: number;
  est_cost_to_complete: number | null;
  unpriced_missing: number;
}

export interface SetCompletion {
  id: string;
  name: string;
  series: string | null;
  release_date: string | null;
  total: number | null;
  printed_total: number | null;
  cards: ChecklistEntry[];
  summary: CompletionSummary;
}
```

- [ ] **Step 2: Add the client functions**

Append to `frontend/src/api/client.ts` (after `searchCards`):
```ts
export async function getSets(q?: string, limit = 50): Promise<SetProgress[]> {
  const params = new URLSearchParams();
  if (q && q.trim()) params.set("q", q.trim());
  params.set("limit", String(limit));
  return expectJson<SetProgress[]>(await fetch(`${BASE}/sets?${params}`));
}

export async function getSetCompletion(setId: string): Promise<SetCompletion> {
  return expectJson<SetCompletion>(await fetch(`${BASE}/sets/${encodeURIComponent(setId)}`));
}
```
Add `SetProgress` and `SetCompletion` to the existing `import type { ... } from "./types";` line in `client.ts`.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat(frontend): getSets + getSetCompletion API client + types"
```

---

### Task 5: Sets.tsx (10th tab) + tests

**Files:**
- Create: `frontend/src/components/Sets.tsx`
- Test: `frontend/src/__tests__/Sets.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/Sets.test.tsx`:
```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import Sets from "../components/Sets";

const noop = () => {};

function stubSets(sets: Array<Record<string, unknown>> = []) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/sets?")) return { ok: true, status: 200, json: async () => sets };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("Sets", () => {
  it("renders the set list with owned/total and a progress bar", async () => {
    stubSets([
      { id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
        total: 2, printed_total: 2, owned: 1, checklist_size: 2, pct_complete: 0.5 },
    ]);
    const { container } = render(<Sets onSelectSet={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    expect(container.textContent ?? "").toContain("1 / 2 owned");
    expect(container.querySelector(".sets-progress-fill")).not.toBeNull();
  });

  it("shows honest 0% for an unowned set, never fabricated", async () => {
    stubSets([
      { id: "promo1", name: "Promo", series: "Promo", release_date: "2020/01/01",
        total: 1, printed_total: 1, owned: 0, checklist_size: 1, pct_complete: 0 },
    ]);
    const { container } = render(<Sets onSelectSet={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("0 / 1 owned");
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("clicking a set calls onSelectSet with the set id", async () => {
    stubSets([
      { id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
        total: 2, printed_total: 2, owned: 0, checklist_size: 2, pct_complete: 0 },
    ]);
    const onSelectSet = vi.fn();
    const { container } = render(<Sets onSelectSet={onSelectSet} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    fireEvent.click(container.querySelector(".sets-row") as HTMLElement);
    expect(onSelectSet).toHaveBeenCalledWith("base1");
  });

  it("renders an empty state when the search matches nothing", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("q=zzz")) return { ok: true, status: 200, json: async () => [] };
      return { ok: true, status: 200, json: async () => [] };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<Sets onSelectSet={noop} />);
    const input = container.querySelector(".sets-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no sets found/i);
    });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/Sets.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

`frontend/src/components/Sets.tsx`:
```tsx
import { useEffect, useRef, useState } from "react";

import { getSets } from "../api/client";
import type { SetProgress } from "../api/types";

interface Props {
  onSelectSet: (setId: string) => void;
}

type State =
  | { kind: "idle" }
  | { kind: "searching"; query: string }
  | { kind: "results"; query: string; sets: SetProgress[] }
  | { kind: "error"; message: string };

export default function Sets({ onSelectSet }: Props) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const reqId = useRef(0);

  useEffect(() => {
    const id = ++reqId.current;
    const trimmed = query.trim();
    if (trimmed === "") {
      setState({ kind: "idle" });
      return;
    }
    setState({ kind: "searching", query: trimmed });
    let cancelled = false;
    const t = setTimeout(() => {
      getSets(trimmed)
        .then((sets) => {
          if (cancelled || id !== reqId.current) return;
          setState({ kind: "results", query: trimmed, sets });
        })
        .catch(() => {
          if (cancelled || id !== reqId.current) return;
          setState({ kind: "error", message: "Could not load sets." });
        });
    }, 250); // debounce, mirroring Browse
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query]);

  return (
    <section className="sets">
      <h2>Sets</h2>
      <p className="muted small">Track completion for every set in the catalog.</p>
      <input
        className="sets-input"
        type="search"
        placeholder="Search sets by name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search sets"
      />

      {state.kind === "searching" && <p className="muted">Searching…</p>}
      {state.kind === "error" && <p className="error">{state.message}</p>}
      {state.kind === "results" && state.sets.length === 0 && (
        <p className="sets-empty muted">No sets found for “{state.query}”.</p>
      )}
      {state.kind === "results" && state.sets.length > 0 && (
        <ul className="sets-list">
          {state.sets.map((s) => {
            const pct = Math.round(s.pct_complete * 100);
            return (
              <li key={s.id}>
                <button className="sets-row" onClick={() => onSelectSet(s.id)}>
                  <span className="sets-row-name">{s.name}</span>
                  <span className="sets-row-meta muted small">
                    {s.series ? `${s.series} · ` : ""}
                    {s.release_date ? s.release_date.slice(0, 4) : ""}
                  </span>
                  <span className="sets-progress">
                    <span
                      className="sets-progress-fill"
                      style={{ width: `${pct}%` }}
                      aria-hidden="true"
                    />
                  </span>
                  <span className="sets-row-count">
                    {s.owned} / {s.checklist_size} owned · {pct}%
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {state.kind === "idle" && (
        <p className="browse-hint muted">Search 170+ sets by name to see completion.</p>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/Sets.test.tsx`
Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Sets.tsx frontend/src/__tests__/Sets.test.tsx
git commit -m "feat(frontend): Sets tab — searchable set list with progress bars"
```

---

### Task 6: SetDetail.tsx overlay + tests

**Files:**
- Create: `frontend/src/components/SetDetail.tsx`
- Test: `frontend/src/__tests__/SetDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/SetDetail.test.tsx`:
```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import SetDetail from "../components/SetDetail";

const noop = () => {};

function stubDetail(body: Record<string, unknown>) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/sets/")) return { ok: true, status: 200, json: async () => body };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

const detail = {
  id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
  total: 3, printed_total: 3,
  cards: [
    { card_id: "base1-1", name: "Bulbasaur", number: "1", rarity: "Common",
      image_small: null, owned: true, market: null, source: null, source_updated_at: null },
    { card_id: "base1-2", name: "Ivysaur", number: "2", rarity: "Uncommon",
      image_small: null, owned: false, market: 3.0, source: "tcgplayer", source_updated_at: "2026/07/28" },
    { card_id: "base1-3", name: "Venusaur", number: "3", rarity: "Rare",
      image_small: null, owned: false, market: null, source: null, source_updated_at: null },
  ],
  summary: { owned: 1, checklist_size: 3, missing: 2, pct_complete: 1 / 3,
    est_cost_to_complete: 3.0, unpriced_missing: 1 },
};

describe("SetDetail", () => {
  it("renders the summary KPIs and the checklist ordered by number", async () => {
    stubDetail(detail);
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("1 / 3 owned");
    expect(text).toContain("33%"); // Math.round(1/3 * 100) = 33
    expect(text).toContain("$3.00"); // est cost to complete
    expect(text).toContain("unpriced: 1");
    // ordered by number
    const nums = [...container.querySelectorAll(".checklist-num")].map((e) => e.textContent);
    expect(nums).toEqual(["1", "2", "3"]);
  });

  it("marks owned cards with an Owned badge and missing cards with a price or 'no market price'", async () => {
    stubDetail(detail);
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const tiles = container.querySelectorAll(".checklist-tile");
    expect(tiles[0].textContent).toMatch(/owned/i);
    expect(tiles[1].textContent).toContain("$3.00");
    expect(tiles[1].textContent).toContain("tcgplayer");
    expect(tiles[2].textContent).toMatch(/no market price/i);
  });

  it("shows 'Complete' and no $0.00 when the set is fully owned", async () => {
    stubDetail({
      ...detail,
      cards: detail.cards.map((c) => ({ ...c, owned: true })),
      summary: { owned: 3, checklist_size: 3, missing: 0, pct_complete: 1,
        est_cost_to_complete: 0.0, unpriced_missing: 0 },
    });
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/complete/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("shows an em dash for est cost when all missing are unpriced", async () => {
    stubDetail({
      ...detail,
      summary: { owned: 0, checklist_size: 3, missing: 3, pct_complete: 0,
        est_cost_to_complete: null, unpriced_missing: 3 },
    });
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.querySelector(".set-detail-cost")?.textContent).toContain("—");
    });
  });

  it("clicking a checklist tile calls onSelectCard with the card id", async () => {
    const spy = stubDetail(detail);
    void spy;
    const onSelectCard = vi.fn();
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={onSelectCard} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    fireEvent.click(container.querySelectorAll(".checklist-tile")[1]);
    expect(onSelectCard).toHaveBeenCalledWith("base1-2");
  });

  it("renders a back button that calls onBack", async () => {
    stubDetail(detail);
    const onBack = vi.fn();
    const { container } = render(<SetDetail setId="base1" onBack={onBack} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const back = [...container.querySelectorAll("button")].find((b) =>
      /back/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/SetDetail.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

`frontend/src/components/SetDetail.tsx`:
```tsx
import { useEffect, useState } from "react";

import { getSetCompletion } from "../api/client";
import { formatMoney } from "../lib/format";
import type { SetCompletion } from "../api/types";

interface Props {
  setId: string;
  onBack: () => void;
  onSelectCard: (cardId: string) => void;
}

export default function SetDetail({ setId, onBack, onSelectCard }: Props) {
  const [data, setData] = useState<SetCompletion | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    getSetCompletion(setId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [setId]);

  if (error) {
    return (
      <section className="set-detail">
        <button className="link card-back" onClick={onBack}>← Back</button>
        <p className="error">Couldn't load this set.</p>
      </section>
    );
  }
  if (!data) {
    return (
      <section className="set-detail">
        <button className="link card-back" onClick={onBack}>← Back</button>
        <div className="skeleton skeleton-block" aria-label="Loading set" />
      </section>
    );
  }

  const s = data.summary;
  const pct = Math.round(s.pct_complete * 100);
  const complete = s.missing === 0;
  const costText =
    s.est_cost_to_complete === null ? "—" : formatMoney(s.est_cost_to_complete);

  return (
    <section className="set-detail">
      <button className="link card-back" onClick={onBack}>← Back</button>

      <div className="set-detail-head">
        <h2>{data.name}</h2>
        <p className="card-meta">
          {data.series ? `${data.series} · ` : ""}
          {data.release_date ? data.release_date.slice(0, 4) : ""}
        </p>
      </div>

      <div className="set-detail-summary">
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value">{s.owned} / {s.checklist_size}</span>
          <span className="muted small">owned</span>
        </div>
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value">{pct}%</span>
          <span className="muted small">complete</span>
        </div>
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value set-detail-cost">
            {complete ? "Complete" : costText}
          </span>
          <span className="muted small">est. cost to complete</span>
        </div>
      </div>

      {!complete && s.unpriced_missing > 0 && (
        <p className="muted small set-detail-unpriced">
          unpriced: {s.unpriced_missing} card{s.unpriced_missing === 1 ? "" : "s"} not in the price index
        </p>
      )}

      <ul className="checklist">
        {data.cards.map((c) => (
          <li key={c.card_id}>
            <button className="checklist-tile" onClick={() => onSelectCard(c.card_id)}>
              <span className="checklist-thumb-wrap">
                {c.image_small ? (
                  <img src={c.image_small} alt="" className="checklist-thumb" />
                ) : (
                  <span className="checklist-thumb placeholder" aria-hidden="true" />
                )}
              </span>
              <span className="checklist-text">
                <span className="checklist-name">{c.name}</span>
                <span className="checklist-num muted small">#{c.number}{c.rarity ? ` · ${c.rarity}` : ""}</span>
                {c.owned ? (
                  <span className="checklist-owned">Owned</span>
                ) : c.market !== null ? (
                  <span className="checklist-price">
                    {formatMoney(c.market)}
                    <span className="muted small">
                      {" "}{c.source}
                      {c.source_updated_at ? ` · as of ${c.source_updated_at}` : ""}
                    </span>
                  </span>
                ) : (
                  <span className="checklist-price muted small">no market price</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

> **Verify `formatMoney`** renders `—` for null and `$3.00` for `3.0` (it does — it's the project's shared formatter; confirm by reading `frontend/src/lib/format.ts` before trusting the test's `$3.00` assertion). If `formatMoney(0)` returns `$0.00`, the "Complete" branch avoids calling it for the complete case (we render "Complete" instead), so the `$0.00` assertion holds.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/SetDetail.test.tsx`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SetDetail.tsx frontend/src/__tests__/SetDetail.test.tsx
git commit -m "feat(frontend): SetDetail overlay — checklist + honest completion summary"
```

---

### Task 7: AppShell wiring (10th tab, overlay, glyph, palette)

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`

- [ ] **Step 1: Read the current AppShell** to confirm exact anchor strings before editing (the file evolves). Re-read lines 1–12 (imports), 71–100 (TabView + state), 150–170 (key map), 183–245 (AnimatePresence + nav), 270–335 (both navs), 580–660 (glyphs), and the command-palette nav command list.

- [ ] **Step 2: Add the import**

After the `Browse` import (or alongside the other component imports):
```tsx
import SetDetail from "./SetDetail";
import Sets from "./Sets";
```

- [ ] **Step 3: Extend `TabView` + `TAB_TITLES`**

Change the `TabView` type to add `"sets"`:
```tsx
type TabView = "home" | "scan" | "vault" | "alerts" | "deals" | "ledger" | "sealed" | "browse" | "sets" | "more";
```
Add to `TAB_TITLES`:
```tsx
sets: "Sets",
```

- [ ] **Step 4: Add `selectedSet` state**

Next to `selectedCard`:
```tsx
const [selectedSet, setSelectedSet] = useState<string | null>(null);
```

- [ ] **Step 5: Add the SetDetail branch to the `<AnimatePresence>`**

The chain is `selectedCard ? CardDetail : view === ...`. Insert a `selectedSet` branch between them so SetDetail opens over the Sets tab and CardDetail stacks on top of it:
```tsx
          {selectedCard ? (
            <PageTransition id="card">
              <CardDetail
                cardId={selectedCard.cardId}
                variant={selectedCard.variant}
                onBack={() => setSelectedCard(null)}
                onWatchCard={(c) => openWatchSheet(c)}
              />
            </PageTransition>
          ) : selectedSet ? (
            <PageTransition id="set">
              <SetDetail
                setId={selectedSet}
                onBack={() => setSelectedSet(null)}
                onSelectCard={(cardId) => setSelectedCard({ cardId })}
              />
            </PageTransition>
          ) : view === "home" ? (
```
And add the Sets tab branch in the view chain (before the `more` fallback):
```tsx
          ) : view === "sets" ? (
            <PageTransition id="sets">
              <Sets onSelectSet={(id) => setSelectedSet(id)} />
            </PageTransition>
          ) : (
            <PageTransition id="more">
              <More />
            </PageTransition>
          )}
```

- [ ] **Step 6: Update the title + key map**

```tsx
const title = selectedCard ? "Card" : selectedSet ? "Sets" : TAB_TITLES[view];
```
Add `sets: "sets"` to the `map` in the keydown listener (the `1`–`9` shortcut only covers digits 1–9; a 10th tab has no digit shortcut — documented follow-up. Adding it to the map is harmless but unreachable by digit; omit to avoid confusion, OR map `"0": "sets"` if you want a shortcut. Decision: omit — the spec defers the shortcut. Leave the map as-is.)

- [ ] **Step 7: Add the tab button to BOTH navs**

In the desktop sidebar (after the Browse `TabButton`):
```tsx
<TabButton label="Sets" active={view === "sets" && !selectedCard} onClick={() => selectTab("sets")} glyph={<SetsGlyph />} />
```
In `DesktopNav` (after Browse):
```tsx
<TabButton label="Sets" active={view === "sets" && !selectedCard} onClick={() => onSelect("sets")} glyph={<SetsGlyph />} />
```

- [ ] **Step 8: Add the `SetsGlyph`**

Next to the other inline glyphs (same viewBox idiom):
```tsx
function SetsGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="4" width="18" height="4" rx="1" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="11" width="18" height="4" rx="1" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="18" width="11" height="3" rx="1" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}
```

- [ ] **Step 9: Add the "Sets" command to the command palette**

Find the nav-commands list in `CommandPalette.tsx` (the palette builds its nav commands from the tab list — re-read it). Add a "Sets" entry mirroring the other nav commands so it is reachable via `⌘K`. (If the palette derives nav commands from a shared `TAB_TITLES`/tab array, adding `sets` to that array in AppShell covers it automatically — verify by reading `CommandPalette.tsx`.)

- [ ] **Step 10: Type-check + run the AppShell/BulkScan tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/__tests__/BulkScan.test.tsx`
Expected: BulkScan's `getByRole("button", { name: "Scan" })` still resolves to one element (the new tab is "Sets", not "Scan"). No TS errors.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/CommandPalette.tsx
git commit -m "feat(frontend): wire Sets tab + SetDetail overlay + SetsGlyph"
```

---

### Task 8: Styles (additive) + bottom-nav scroll

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Read the end of `styles.css`** and the existing `.bottom-nav` rule to append additive styles without renaming anything.

- [ ] **Step 2: Append the set-completion styles**

Append (additive — new selectors only):
```css
/* ---- Phase 06: Set completion ---- */
.sets { display: flex; flex-direction: column; gap: var(--sp-3); }
.sets-input {
  width: 100%; max-width: 480px;
  padding: var(--sp-2) var(--sp-3);
  background: var(--glass-bg); border: 1px solid var(--glass-border);
  border-radius: var(--r-2); color: var(--fg);
}
.sets-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-2); }
.sets-row {
  display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto;
  align-items: center; gap: var(--sp-1) var(--sp-3);
  width: 100%; text-align: left; padding: var(--sp-3);
  background: var(--glass-bg); border: 1px solid var(--glass-border);
  border-radius: var(--r-2); cursor: pointer; color: var(--fg);
}
.sets-row:hover { border-color: var(--accent); }
.sets-row-name { font-weight: 600; }
.sets-row-meta { grid-column: 1; }
.sets-row-count { grid-column: 2; grid-row: 1 / span 2; align-self: center; font-variant-numeric: tabular-nums; }
.sets-progress {
  grid-column: 1; height: 6px; border-radius: 999px;
  background: var(--line); overflow: hidden;
}
.sets-progress-fill { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.4s ease; }

.set-detail { display: flex; flex-direction: column; gap: var(--sp-3); }
.set-detail-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); }
.set-detail-kpi { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-3); background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--r-2); }
.set-detail-kpi-value { font-size: 1.4rem; font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
.set-detail-cost { color: var(--fg); }
.set-detail-unpriced { font-style: italic; }

.checklist { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--sp-2); }
.checklist-tile {
  display: flex; flex-direction: column; gap: var(--sp-1); text-align: left;
  padding: var(--sp-2); background: var(--glass-bg); border: 1px solid var(--glass-border);
  border-radius: var(--r-2); cursor: pointer; color: var(--fg);
}
.checklist-tile:hover { border-color: var(--accent); }
.checklist-thumb-wrap { display: flex; justify-content: center; }
.checklist-thumb { width: 100%; max-width: 96px; aspect-ratio: 3 / 4; object-fit: contain; border-radius: var(--r-1); }
.checklist-thumb.placeholder { background: var(--surface); }
.checklist-text { display: flex; flex-direction: column; gap: 2px; }
.checklist-name { font-weight: 600; font-size: 0.9rem; }
.checklist-num { font-size: 0.75rem; }
.checklist-owned { color: var(--ok); font-weight: 600; font-size: 0.8rem; }
.checklist-price { color: var(--fg); font-weight: 600; font-size: 0.85rem; }

/* 10 tabs fit on mobile without crowding (visual-only; no test queries layout). */
.bottom-nav { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.bottom-nav::-webkit-scrollbar { height: 0; }

@media (prefers-reduced-motion: reduce) {
  .sets-progress-fill { transition: none; }
}
@media (min-width: 880px) {
  .sets-list { grid-template-columns: repeat(2, 1fr); }
}
```

- [ ] **Step 3: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: all tests green (prior 165 + 10 new = 175); build clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat(frontend): set-completion styles + scrollable bottom-nav for 10 tabs"
```

---

### Task 9: Docs + memory + push

**Files:**
- Modify: `AI_CONTEXT.md`, `PROJECT.md`, `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md`, `MEMORY.md`

- [ ] **Step 1: Update `AI_CONTEXT.md`**

- Roadmap: change row `6 | Set-completion optimizer | Planned` → `✅ Complete 2026-08-22 (§20) — frontend + backend; 584 backend + 175 frontend tests green; 105-scan baseline untouched`.
- Bump `**Tests:** 568 backend (pytest) + 165 frontend (vitest).` → `584 backend + 175 frontend`.
- Append `## 20. Phase 06 — Set-completion optimizer (2026-08-22)` mirroring the §19 structure: goal, `CompletionService` + routes, frontend (Sets tab + SetDetail overlay), do-not-break contract (10th tab named "Sets"), sacred constraints held (latest_price, func.lower.like, honest 0%/—), deferred follow-ups (per-variant, cheapest-listing, `0` shortcut).

- [ ] **Step 2: Update `PROJECT.md`**

- Update the intro "Next:" line to remove set-completion from the deferred list and append: "Set-completion optimizer (Phase 06 — per-set owned/missing checklist + honest cost to complete via latest_price) shipped 2026-08-22 — see [plan](docs/superpowers/plans/2026-08-21-set-completion.md)."
- Append a `## Set-completion optimizer — shipped 2026-08-22` section mirroring the Grading Studio section.

- [ ] **Step 3: Update memory**

- `pokemon-card-platform-project.md`: append a `**Set-completion optimizer (2026-08-22):**` paragraph (completion service, routes, Sets tab + SetDetail overlay, 10th tab, honest 0%/—, latest_price, 584/175 tests, pushed). Update the "How to verify" line to `584 backend + 175 frontend`.
- `MEMORY.md`: update the Pokémon card platform hook line to mention Phase 06 shipped + the new test counts.

- [ ] **Step 4: Final verify**

Run:
```bash
cd C:/ClaudeKnowledge
backend/.venv/Scripts/python -m pytest -q
cd frontend && npx vitest run && npm run build
cd .. && git status --short
```
Expected: 584 backend + 175 frontend green; build clean; only intended files changed.

- [ ] **Step 5: Commit + push**

```bash
git add AI_CONTEXT.md PROJECT.md
git commit -m "docs: Phase 06 set-completion optimizer — AI_CONTEXT §20 + PROJECT.md"
git push origin main
```

---

## Self-Review

**1. Spec coverage:**
- §3.1 `list_sets` (grouped owned + checklist counts, `func.lower.like`, release_date desc, pct 0/no div-by-zero) → T1 tests + impl. ✓
- §3.1 `set_detail` (natural sort, owned flags, latest_price per missing, summary honest costs, `""`→None) → T1. ✓
- §3.2 routes (`GET /sets` q/limit 422, `GET /sets/{id}` 404) → T3. ✓
- §3.3 Pydantic models → T2. ✓
- §3.4 frontend (Sets, SetDetail, client, AppShell, palette) → T4–T7. ✓
- §3.5 honest empty states → T1, T5, T6 tests. ✓
- §6 do-not-break (10th tab "Sets", distinct classes, bottom-nav visual-only) → T7, T8. ✓
- §7 sacred constraints → T1 (latest_price, func.lower, `""`→None), T3 (read-only). ✓

**2. Placeholder scan:** every step has complete code or a precise read-then-edit instruction (T7/T8 require re-reading AppShell/styles because those files evolve — the instruction is explicit, not a placeholder). No "TBD"/"TODO".

**3. Type consistency:** `SetProgress`/`SetCompletion`/`ChecklistEntry`/`CompletionSummary` field names are identical across the Python dataclasses (T1), Pydantic models (T2), JSON (T3 tests), TS types (T4), and components (T5/T6). `est_cost_to_complete` (snake_case) is used in Python + JSON + TS (the TS types use snake_case to match the wire — consistent with the existing `CollectionItem`/`Portfolio` types in `types.ts`, which are snake_case). `pct_complete` likewise. `checklist_size`, `unpriced_missing` consistent throughout.

**4. Open question flagged for the implementer:** T6 Step 3 notes to verify `formatMoney`'s exact output (`$3.00` for `3.0`, `—` for null) before trusting the test assertion — the test will catch any mismatch, but the implementer should confirm the formatter rather than assume. The "Complete" branch deliberately avoids `formatMoney(0)` so no `$0.00` leaks.