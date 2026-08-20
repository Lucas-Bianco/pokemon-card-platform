# Sealed Purchase Ledger + Profit Tracker + Google Sheets Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reseller's sealed-product purchase ledger — log boxes/packs bought, track
live profit (median sold comps via the 05c sealed provider), and sync the ledger to a
Google Sheet via OAuth browser sign-in.

**Architecture:** Two new tables (`sealed_purchases` user-editable + `sealed_valuations`
append-only market snapshots, auto-provisioned by `create_all()`). A `LedgerService` does
CRUD + on-demand valuation refresh (reuses `EbayListingsProvider.fetch_sold_listings_by_query`
+ `statistics.median`) + read-only profit. REST + CLI + an 8th "Ledger" frontend tab. A
`GoogleSheetsClient` (google-auth-oauthlib + google-api-python-client) does OAuth browser
sign-in + full-tab-overwrite sync. Local ledger is source of truth; Sheets is a mirror that
degrades to honest "not configured" with zero Google setup.

**Tech Stack:** Python 3.12 (backend/.venv ONLY — system is 3.14, no ML wheels), FastAPI,
SQLAlchemy 2 + SQLite, Pydantic v2. Vite + React 19 + TypeScript strict. google-auth-oauthlib
+ google-api-python-client (new deps).

**Sibling spec:** `docs/superpowers/specs/2026-08-20-sealed-ledger-design.md` (read it — §7
profit math and §8 OAuth/sync are authoritative).

**Sacred constraints (do not break — verbatim from project):** never resolve "the latest
price" ad-hoc — profit reads the latest persisted `SealedValuation`; the only live fetch is
the explicit Refresh action which INSERTs a new immutable snapshot. Valuations are
append-only (insert, never update); latest = max(id) per purchase. Honest empty states —
`value_per_unit`/`profit`/`profit_pct` null when no valuation; UI shows `—` via
`formatMoney(null)`, never `$0`. Providers degrade to `[]`, never raise. No eBay key → no
valuation (honest), never an error. Google not configured → `synced=False`, never raises.
Always surface staleness (`market_fetched_at` + `market_source`). `UtcDateTime` for
`bought_at`/`fetched_at`/`created_at` (tz-aware). Never delete anything under `data/`. OAuth
token + client secret live under `data/` (gitignored) — never commit them. Only edit files
inside `C:\ClaudeKnowledge`. Commit per task (scoped — never `git add -A`; never stage
unrelated root dirs). Ask before destructive/irreversible commands.

**Verify commands:** `backend/.venv/Scripts/python -m pytest -q` (530 → grows),
`npm --prefix frontend test -- --run` (115 → grows), `npm --prefix frontend run build`,
`npm --prefix site run build`, 105-scan baseline
`backend/.venv/Scripts/python backend/scripts/evaluate_detection.py` (0 regressions).

---

## Task 1: DB models — SealedPurchase + SealedValuation

**Files:**
- Modify: `backend/src/cardplatform/db/models.py` (append two `Base` subclasses)
- Test: `backend/tests/test_sealed_ledger_models.py`

The existing `Base`, `UtcDateTime`, `_utcnow`, and column types (`Integer`, `Float`, `String`,
`ForeignKey`, `Index`) are already imported in `models.py`. New tables are auto-provisioned
by `Database.create_all()` → `Base.metadata.create_all` — **no migration entry needed**.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_sealed_ledger_models.py`:

```python
from datetime import datetime, timezone

from cardplatform.db.models import SealedPurchase, SealedValuation


def test_can_persist_a_purchase(db):
    p = SealedPurchase(
        query="scarlet violet booster box",
        product_type="booster_box",
        quantity=2,
        cost_per_unit=120.0,
        source="eBay",
        listing_url="https://example.com/x",
        notes="sealed case",
        bought_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )
    db.add(p)
    db.commit()
    got = db.get(SealedPurchase, p.id)
    assert got is not None
    assert got.query == "scarlet violet booster box"
    assert got.quantity == 2
    assert got.cost_per_unit == 120.0
    assert got.created_at.tzinfo is not None  # UtcDateTime re-attaches UTC


def test_purchase_defaults_quantity_and_timestamps(db):
    p = SealedPurchase(query="pokemon 151 booster bundle", cost_per_unit=27.5)
    db.add(p)
    db.commit()
    got = db.get(SealedPurchase, p.id)
    assert got.quantity == 1
    assert got.product_type is None
    assert got.bought_at is not None and got.bought_at.tzinfo is not None
    assert got.created_at.tzinfo is not None


def test_can_persist_a_valuation_and_latest_is_max_id(db):
    p = SealedPurchase(query="etb", cost_per_unit=50.0)
    db.add(p)
    db.commit()
    v1 = SealedValuation(purchase_id=p.id, value_per_unit=60.0, comp_count=5)
    v2 = SealedValuation(purchase_id=p.id, value_per_unit=64.0, comp_count=6)
    db.add_all([v1, v2])
    db.commit()
    rows = (
        db.query(SealedValuation)
        .filter(SealedValuation.purchase_id == p.id)
        .order_by(SealedValuation.id.desc())
        .all()
    )
    assert len(rows) == 2  # append-only: both kept
    assert rows[0].value_per_unit == 64.0  # latest = max(id)
    assert rows[0].fetched_at.tzinfo is not None
    assert rows[1].value_per_unit == 60.0


def test_valuation_source_defaults_to_ebay_sold_median(db):
    p = SealedPurchase(query="pack", cost_per_unit=5.0)
    db.add(p)
    db.commit()
    v = SealedValuation(purchase_id=p.id, value_per_unit=6.0, comp_count=3)
    db.add(v)
    db.commit()
    assert db.get(SealedValuation, v.id).source == "ebay_sold_median"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'SealedPurchase'`.

- [ ] **Step 3: Add the two models**

Append to `backend/src/cardplatform/db/models.py` (after the last model class; keep the
trailing newline):

```python
class SealedPurchase(Base):
    """A reseller's logged sealed-product buy. User-editable (distinct from recognition
    snapshots — resellers correct mistakes). The immutable core of a ledger entry."""

    __tablename__ = "sealed_purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String, index=True)
    product_type: Mapped[str | None] = mapped_column(String, default=None)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    cost_per_unit: Mapped[float] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String, default=None)
    listing_url: Mapped[str | None] = mapped_column(String, default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    bought_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SealedValuation(Base):
    """Append-only market snapshot for a purchase — the sealed surface's price-snapshot
    store (mirrors PriceSnapshot immutability: insert, never update). Latest per purchase
    = max(id). Sourced via the eBay sold-comps provider + median; never fabricated."""

    __tablename__ = "sealed_valuations"
    __table_args__ = (Index("ix_valuation_lookup", "purchase_id", "fetched_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("sealed_purchases.id"), index=True)
    value_per_unit: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String, default="ebay_sold_median")
    comp_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_models.py -q`
Expected: PASS (4).

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (534 — 530 + 4 new; the new tables auto-create).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/db/models.py backend/tests/test_sealed_ledger_models.py
git commit -m "feat(ledger): SealedPurchase + SealedValuation models (Phase 05d T1)"
```

---

## Task 2: LedgerService — CRUD + profit + valuation refresh

**Files:**
- Create: `backend/src/cardplatform/sealed/ledger.py`
- Test: `backend/tests/test_sealed_ledger_service.py`

Reuses `EbayListingsProvider` + `statistics.median` (self-contained — does not import the
private `_median` from `engine.py`). Read-only profit reads the latest persisted valuation;
Refresh is the only write path for valuations (INSERT, never update).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_sealed_ledger_service.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from cardplatform.db.models import SealedPurchase, SealedValuation
from cardplatform.sealed.ledger import (
    LedgerEntry,
    LedgerService,
    ValuationRefreshResult,
)
from cardplatform.sealed.provider import SealedSoldComp


@dataclass
class FakeProvider:
    name: str = "fake"
    comps_by_query: dict = None
    raise_on_call: bool = False

    def __post_init__(self):
        if self.comps_by_query is None:
            self.comps_by_query = {}

    def fetch_listings_by_query(self, query):
        return []

    def fetch_sold_listings_by_query(self, query, limit=3):
        if self.raise_on_call:
            raise RuntimeError("provider blew up")
        return list(self.comps_by_query.get(query, []))


def _comp(price, listing_id="c1"):
    return SealedSoldComp(query="q", listing_id=listing_id, price=price)


def _service(db, provider=None, settings=None):
    return LedgerService(db, provider=provider or FakeProvider(), settings=settings)


def test_create_purchase_validates_inputs(db):
    svc = _service(db)
    with pytest.raises(ValueError):
        svc.create_purchase(query="", cost_per_unit=10.0)
    with pytest.raises(ValueError):
        svc.create_purchase(query="box", quantity=0, cost_per_unit=10.0)
    with pytest.raises(ValueError):
        svc.create_purchase(query="box", cost_per_unit=-1.0)


def test_create_purchase_persists_and_returns(db):
    svc = _service(db)
    p = svc.create_purchase(
        query="scarlet violet booster box",
        product_type="booster_box",
        quantity=2,
        cost_per_unit=120.0,
        source="eBay",
    )
    assert p.id is not None
    assert p.quantity == 2
    assert db.get(SealedPurchase, p.id).query == "scarlet violet booster box"


def test_delete_purchase_removes_valuations_too(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", cost_per_unit=10.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=12.0, comp_count=3))
    db.commit()
    assert svc.delete_purchase(p.id) is True
    assert db.get(SealedPurchase, p.id) is None
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 0


def test_delete_missing_purchase_returns_false(db):
    svc = _service(db)
    assert svc.delete_purchase(999) is False


def test_list_ledger_computes_profit_from_latest_valuation(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", quantity=2, cost_per_unit=100.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=130.0, comp_count=5))
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=150.0, comp_count=6))  # latest
    db.commit()
    entries = svc.list_ledger()
    assert len(entries) == 1
    e = entries[0]
    assert e.total_cost == 200.0
    assert e.value_per_unit == 150.0  # latest = max(id)
    assert e.total_current_value == 300.0
    assert e.profit == 100.0
    assert e.profit_pct == 0.5
    assert e.valued is True
    assert e.market_source == "ebay_sold_median"


def test_list_ledger_unvalued_purchase_has_nulls_never_zero(db):
    svc = _service(db)
    svc.create_purchase(query="box", quantity=1, cost_per_unit=100.0)
    e = svc.list_ledger()[0]
    assert e.value_per_unit is None
    assert e.total_current_value is None
    assert e.profit is None
    assert e.profit_pct is None
    assert e.valued is False
    assert e.total_cost == 100.0  # cost is known


def test_list_ledger_profit_pct_null_when_cost_zero(db):
    svc = _service(db)
    p = svc.create_purchase(query="gift", quantity=1, cost_per_unit=0.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=10.0, comp_count=2))
    db.commit()
    e = svc.list_ledger()[0]
    assert e.profit == 10.0
    assert e.profit_pct is None  # division by zero guarded


def test_refresh_valuation_inserts_median_snapshot(db):
    provider = FakeProvider(comps_by_query={"box": [_comp(60.0), _comp(64.0), _comp(70.0)]})
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    v = svc.refresh_valuation(p.id)
    assert v is not None
    assert v.value_per_unit == 64.0  # median of [60,64,70]
    assert v.comp_count == 3
    assert v.source == "ebay_sold_median"
    # append-only: a second refresh adds a second row
    v2 = svc.refresh_valuation(p.id)
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 2


def test_refresh_valuation_no_comps_returns_none_no_row(db):
    provider = FakeProvider(comps_by_query={"box": []})
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    assert svc.refresh_valuation(p.id) is None
    assert db.query(SealedValuation).filter_by(purchase_id=p.id).count() == 0


def test_refresh_valuation_provider_raises_degrades_to_none(db):
    provider = FakeProvider(raise_on_call=True)
    svc = _service(db, provider=provider)
    p = svc.create_purchase(query="box", cost_per_unit=50.0)
    # The real provider never raises; a fake that does must still not blow up the service.
    assert svc.refresh_valuation(p.id) is None


def test_refresh_all_summarizes_valued_and_skipped(db):
    provider = FakeProvider(
        comps_by_query={
            "box": [_comp(60.0), _comp(64.0)],          # valued
            "pack": [],                                  # no comps -> skipped
        }
    )
    svc = _service(db, provider=provider)
    svc.create_purchase(query="box", cost_per_unit=50.0)
    svc.create_purchase(query="pack", cost_per_unit=5.0)
    result = svc.refresh_all()
    assert isinstance(result, ValuationRefreshResult)
    assert result.valued == 1
    assert result.skipped_no_comps == 1
    assert result.skipped_no_key is False
```

Note: `test_refresh_valuation_provider_raises_degrades_to_none` asserts the service wraps
the provider call in a try/except that degrades to `None` (the real provider never raises,
but the service must be defensive — never propagate a provider error to the API layer).

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'LedgerService'`.

- [ ] **Step 3: Implement the service**

`backend/src/cardplatform/sealed/ledger.py`:

```python
"""Sealed purchase ledger + profit tracker.

Reseller-facing: log sealed boxes/packs bought, fetch current market value per unit
(median of recent eBay sold comps via the 05c sealed provider), store append-only
valuations, and compute live profit.

Sacred constraints held:
- Profit reads the latest persisted SealedValuation (never resolves a price ad hoc).
- Refresh is the only write path for valuations and it INSERTs (append-only, never update);
  latest = max(id) per purchase.
- No eBay key / no comps / provider error -> no valuation inserted (honest), never raises.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, default_settings
from cardplatform.db.models import SealedPurchase, SealedValuation
from cardplatform.sealed.provider import SealedListingsProvider


@dataclass(frozen=True)
class LedgerEntry:
    """One row of the ledger view — a purchase joined with its latest valuation +
    read-only profit math. Nulls are honest (unvalued), never $0."""

    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    total_cost: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime
    value_per_unit: float | None
    total_current_value: float | None
    profit: float | None
    profit_pct: float | None
    market_fetched_at: datetime | None
    market_source: str | None
    valued: bool


@dataclass(frozen=True)
class ValuationRefreshResult:
    valued: int
    skipped_no_comps: int
    skipped_no_key: bool


class LedgerService:
    """CRUD + on-demand valuation refresh + read-only profit. The provider is used only by
    refresh_*; list_ledger is pure DB read."""

    def __init__(
        self,
        session: Session,
        provider: SealedListingsProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or default_settings
        if provider is None:
            # Lazy import to avoid a hard import cycle at module load.
            from cardplatform.prices.ebay_listings import EbayListingsProvider

            provider = EbayListingsProvider(self.settings)
        self.provider = provider

    # ---- CRUD ----

    def create_purchase(
        self,
        *,
        query: str,
        product_type: str | None = None,
        quantity: int = 1,
        cost_per_unit: float,
        source: str | None = None,
        listing_url: str | None = None,
        notes: str | None = None,
        bought_at: datetime | None = None,
    ) -> SealedPurchase:
        q = (query or "").strip()
        if not q:
            raise ValueError("query is required")
        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        if cost_per_unit < 0:
            raise ValueError("cost_per_unit must be >= 0")
        purchase = SealedPurchase(
            query=q,
            product_type=product_type,
            quantity=quantity,
            cost_per_unit=cost_per_unit,
            source=source,
            listing_url=listing_url,
            notes=notes,
            bought_at=bought_at,
        )
        self.session.add(purchase)
        self.session.commit()
        self.session.refresh(purchase)
        return purchase

    def get_purchase(self, purchase_id: int) -> SealedPurchase | None:
        return self.session.get(SealedPurchase, purchase_id)

    def delete_purchase(self, purchase_id: int) -> bool:
        purchase = self.session.get(SealedPurchase, purchase_id)
        if purchase is None:
            return False
        # Explicit cascade — do not rely on a SQLite FK-cascade pragma being enabled.
        self.session.query(SealedValuation).filter(
            SealedValuation.purchase_id == purchase_id
        ).delete(synchronize_session=False)
        self.session.delete(purchase)
        self.session.commit()
        return True

    # ---- valuations ----

    def latest_valuation(self, purchase_id: int) -> SealedValuation | None:
        stmt = (
            select(SealedValuation)
            .where(SealedValuation.purchase_id == purchase_id)
            .order_by(SealedValuation.id.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def refresh_valuation(self, purchase_id: int) -> SealedValuation | None:
        purchase = self.session.get(SealedPurchase, purchase_id)
        if purchase is None:
            return None
        try:
            comps = self.provider.fetch_sold_listings_by_query(
                purchase.query, self.settings.sealed_sold_comp_limit
            )
        except Exception:  # providers never raise in practice; be defensive anyway.
            return None
        prices = [c.price for c in comps if c.price is not None]
        if not prices:
            return None  # no comps -> no snapshot, honest
        value = statistics.median(prices)
        v = SealedValuation(
            purchase_id=purchase.id,
            value_per_unit=value,
            source="ebay_sold_median",
            comp_count=len(prices),
        )
        self.session.add(v)
        self.session.commit()
        self.session.refresh(v)
        return v

    def refresh_all(self) -> ValuationRefreshResult:
        purchases = self.session.execute(
            select(SealedPurchase).order_by(SealedPurchase.id.asc())
        ).scalars().all()
        # No eBay key -> the provider returns [] for every query; detect once up front.
        key_set = bool(getattr(self.settings, "listings_api_key", None))
        valued = 0
        skipped_no_comps = 0
        for p in purchases:
            v = self.refresh_valuation(p.id)
            if v is not None:
                valued += 1
            else:
                skipped_no_comps += 1
        return ValuationRefreshResult(
            valued=valued,
            skipped_no_comps=skipped_no_comps,
            skipped_no_key=not key_set,
        )

    # ---- read-only profit ----

    def list_ledger(self) -> list[LedgerEntry]:
        purchases = self.session.execute(
            select(SealedPurchase).order_by(SealedPurchase.bought_at.desc())
        ).scalars().all()
        entries: list[LedgerEntry] = []
        for p in purchases:
            latest = self.latest_valuation(p.id)
            total_cost = p.quantity * p.cost_per_unit
            value_per_unit = latest.value_per_unit if latest is not None else None
            total_current_value = (
                value_per_unit * p.quantity if value_per_unit is not None else None
            )
            profit = (
                total_current_value - total_cost
                if total_current_value is not None
                else None
            )
            profit_pct = (
                profit / total_cost
                if profit is not None and total_cost > 0
                else None
            )
            entries.append(
                LedgerEntry(
                    id=p.id,
                    query=p.query,
                    product_type=p.product_type,
                    quantity=p.quantity,
                    cost_per_unit=p.cost_per_unit,
                    total_cost=total_cost,
                    source=p.source,
                    listing_url=p.listing_url,
                    notes=p.notes,
                    bought_at=p.bought_at,
                    created_at=p.created_at,
                    value_per_unit=value_per_unit,
                    total_current_value=total_current_value,
                    profit=profit,
                    profit_pct=profit_pct,
                    market_fetched_at=latest.fetched_at if latest is not None else None,
                    market_source=latest.source if latest is not None else None,
                    valued=latest is not None,
                )
            )
        return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_service.py -q`
Expected: PASS (11).

- [ ] **Step 5: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (545 — 534 + 11).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/sealed/ledger.py backend/tests/test_sealed_ledger_service.py
git commit -m "feat(ledger): LedgerService CRUD + profit + valuation refresh (Phase 05d T2)"
```

---

## Task 3: API routes + wire models

**Files:**
- Modify: `backend/src/cardplatform/sealed/api_models.py` (add ledger wire models)
- Modify: `backend/src/cardplatform/api.py` (add `/sealed/ledger` routes)
- Test: `backend/tests/test_sealed_ledger_api.py`

Write routes mirror `POST /watchlist` (write via `session.add`/`commit`/`refresh` +
`model_validate`) and `DELETE /watchlist/{id}` (`session.get` → 404 → delete → `204`). The
read route mirrors `GET /sealed/deals` but takes a DB session.

**Session override in tests:** the API uses `Depends(get_session)` backed by the module-level
`_database` (real `data/` SQLite). Tests must override it. Before writing tests, **read
`backend/tests/test_watchlist_api.py`** (or whichever existing test exercises `POST /watchlist`
/ `DELETE /watchlist`) to learn the exact dependency-override idiom this repo uses
(`app.dependency_overrides[get_session] = ...` or a fixture), then mirror it verbatim. Do not
invent a new pattern.

- [ ] **Step 1: Add the wire models**

Append to `backend/src/cardplatform/sealed/api_models.py`:

```python
class SealedPurchaseIn(BaseModel):
    query: str
    product_type: str | None = None
    quantity: int = Field(default=1, ge=1)
    cost_per_unit: float = Field(ge=0)
    source: str | None = None
    listing_url: str | None = None
    notes: str | None = None
    bought_at: datetime | None = None


class SealedPurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime


class SealedLedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    total_cost: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime
    value_per_unit: float | None
    total_current_value: float | None
    profit: float | None
    profit_pct: float | None
    market_fetched_at: datetime | None
    market_source: str | None
    valued: bool


class SealedLedgerResponse(BaseModel):
    purchases: list[SealedLedgerEntryOut]
    listings_unavailable: bool


class ValuationRefreshResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    valued: int
    skipped_no_comps: int
    skipped_no_key: bool


class SheetsSyncResultOut(BaseModel):
    synced: bool
    rows: int
    reason: str | None = None
```

If `datetime` and `Field` are not already imported at the top of `api_models.py`, add them
(`from datetime import datetime` and `from pydantic import Field`). Check the existing
imports first and only add what is missing.

- [ ] **Step 2: Write the failing API tests**

`backend/tests/test_sealed_ledger_api.py`:

```python
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import SealedValuation
from cardplatform.sealed.ledger import LedgerService
from cardplatform.sealed.provider import SealedSoldComp


def _client(monkeypatch, db, key="app-id"):
    """Mirror the existing write-route test idiom for overriding get_session (read
    test_watchlist_api.py and copy the exact pattern). The shape below is the standard
    FastAPI dependency override; adjust to match the repo's actual fixture if it differs."""
    app = create_app()
    monkeypatch.setattr(
        "cardplatform.api.settings",
        Settings(listings_api_key=key, sealed_sold_comp_limit=10),
    )

    def _override_session():
        yield db

    app.dependency_overrides[get_session] = _override_session
    return TestClient(app)


def _comp(price, listing_id="c1"):
    return SealedSoldComp(query="box", listing_id=listing_id, price=price)


def _stub_provider(monkeypatch, comps=None):
    """Stub EbayListingsProvider.fetch_sold_listings_by_query at the source the route
    imports (mirror test_sealed_deals_api's engine-stub approach)."""
    comps = comps if comps is not None else [_comp(60.0), _comp(64.0), _comp(70.0)]

    class _P:
        name = "fake"

        def fetch_listings_by_query(self, query):
            return []

        def fetch_sold_listings_by_query(self, query, limit=3):
            return list(comps)

    # The route constructs EbayListingsProvider(settings); patch its query-keyed fetch.
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.EbayListingsProvider.fetch_sold_listings_by_query",
        _P().fetch_sold_listings_by_query,
    )


def test_get_ledger_empty_when_no_purchases(db, monkeypatch):
    client = _client(monkeypatch, db)
    r = client.get("/api/sealed/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["purchases"] == []
    assert body["listings_unavailable"] is False  # key is set in _client


def test_get_ledger_listings_unavailable_when_no_key(db, monkeypatch):
    client = _client(monkeypatch, db, key=None)
    r = client.get("/api/sealed/ledger")
    assert r.status_code == 200
    assert r.json()["listings_unavailable"] is True


def test_post_ledger_creates_purchase(db, monkeypatch):
    client = _client(monkeypatch, db)
    r = client.post(
        "/api/sealed/ledger",
        json={"query": "scarlet violet booster box", "quantity": 2, "cost_per_unit": 120.0},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["quantity"] == 2
    assert body["query"] == "scarlet violet booster box"


def test_post_ledger_rejects_bad_input(db, monkeypatch):
    client = _client(monkeypatch, db)
    assert client.post("/api/sealed/ledger", json={"query": "", "cost_per_unit": 10.0}).status_code == 422
    assert client.post("/api/sealed/ledger", json={"query": "x", "quantity": 0, "cost_per_unit": 10.0}).status_code == 422
    assert client.post("/api/sealed/ledger", json={"query": "x", "cost_per_unit": -5.0}).status_code == 422


def test_delete_ledger_404_then_204(db, monkeypatch):
    client = _client(monkeypatch, db)
    assert client.delete("/api/sealed/ledger/999").status_code == 404
    pid = client.post("/api/sealed/ledger", json={"query": "box", "cost_per_unit": 10.0}).json()["id"]
    assert client.delete(f"/api/sealed/ledger/{pid}").status_code == 204


def test_valuate_all_refreshes_and_returns_result(db, monkeypatch):
    _stub_provider(monkeypatch)
    client = _client(monkeypatch, db)
    client.post("/api/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0})
    r = client.post("/api/sealed/ledger/valuate")
    assert r.status_code == 200
    body = r.json()
    assert body["valued"] == 1
    assert body["skipped_no_comps"] == 0
    assert body["skipped_no_key"] is False
    # ledger now shows a valued entry with profit, never $0
    entries = client.get("/api/sealed/ledger").json()["purchases"]
    assert entries[0]["valued"] is True
    assert entries[0]["value_per_unit"] == 64.0  # median of [60,64,70]
    assert entries[0]["profit"] is not None


def test_valuate_all_no_key_skips(db, monkeypatch):
    _stub_provider(monkeypatch, comps=[])
    client = _client(monkeypatch, db, key=None)
    client.post("/api/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0})
    r = client.post("/api/sealed/ledger/valuate")
    body = r.json()
    assert body["valued"] == 0
    assert body["skipped_no_key"] is True


def test_valuate_one_returns_refreshed_entry(db, monkeypatch):
    _stub_provider(monkeypatch)
    client = _client(monkeypatch, db)
    pid = client.post("/api/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0}).json()["id"]
    r = client.post(f"/api/sealed/ledger/{pid}/valuate")
    assert r.status_code == 200
    body = r.json()
    assert body["valued"] is True
    assert body["value_per_unit"] == 64.0
    assert client.post("/api/sealed/ledger/999/valuate").status_code == 404
```

If the repo's existing write-route tests use a different session-override mechanism (e.g. a
`db_session` fixture that patches `cardplatform.api._database`), adopt that instead and
adjust `_client` accordingly — the assertions stay the same.

- [ ] **Step 3: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_api.py -q`
Expected: FAIL — routes do not exist yet (404 / AttributeError).

- [ ] **Step 4: Add the routes**

In `backend/src/cardplatform/api.py`, first ensure these imports are present (add any
missing; mirror the existing import block near the top):

```python
from cardplatform.sealed.api_models import (
    SealedDealsResponse,  # existing
    SealedDealAssessmentOut,  # existing
    SealedPricePointOut,  # existing
    SealedThresholdsOut,  # existing
    SealedPurchaseIn,
    SealedPurchaseOut,
    SealedLedgerEntryOut,
    SealedLedgerResponse,
    ValuationRefreshResultOut,
    SheetsSyncResultOut,
)
from cardplatform.sealed.ledger import LedgerService, LedgerEntry
```

(Only add `SealedPurchaseIn`...`SheetsSyncResultOut` and `LedgerService, LedgerEntry` to the
imports — do not duplicate the existing sealed imports.)

Then add these routes immediately after the existing `@app.get("/sealed/deals")` route (keep
the read route without a session, then the ledger routes with sessions):

```python
@app.get("/sealed/ledger", response_model=SealedLedgerResponse)
def sealed_ledger(session: Session = Depends(get_session)) -> SealedLedgerResponse:
    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    entries = svc.list_ledger()
    return SealedLedgerResponse(
        purchases=[SealedLedgerEntryOut.model_validate(e) for e in entries],
        listings_unavailable=not bool(settings.listings_api_key),
    )


@app.post("/sealed/ledger", response_model=SealedPurchaseOut, status_code=201)
def create_sealed_purchase(
    payload: SealedPurchaseIn, session: Session = Depends(get_session)
) -> SealedPurchaseOut:
    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    try:
        p = svc.create_purchase(
            query=payload.query,
            product_type=payload.product_type,
            quantity=payload.quantity,
            cost_per_unit=payload.cost_per_unit,
            source=payload.source,
            listing_url=payload.listing_url,
            notes=payload.notes,
            bought_at=payload.bought_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SealedPurchaseOut.model_validate(p)


@app.delete("/sealed/ledger/{purchase_id}")
def delete_sealed_purchase(
    purchase_id: int, session: Session = Depends(get_session)
) -> Response:
    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    if not svc.delete_purchase(purchase_id):
        raise HTTPException(status_code=404, detail="unknown purchase")
    return Response(status_code=204)


@app.post("/sealed/ledger/valuate", response_model=ValuationRefreshResultOut)
def valuate_sealed_ledger(session: Session = Depends(get_session)) -> ValuationRefreshResultOut:
    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    return ValuationRefreshResultOut.model_validate(svc.refresh_all())


@app.post("/sealed/ledger/{purchase_id}/valuate", response_model=SealedLedgerEntryOut)
def valuate_one_sealed_purchase(
    purchase_id: int, session: Session = Depends(get_session)
) -> SealedLedgerEntryOut:
    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    if svc.get_purchase(purchase_id) is None:
        raise HTTPException(status_code=404, detail="unknown purchase")
    svc.refresh_valuation(purchase_id)
    entries = svc.list_ledger()
    entry = next((e for e in entries if e.id == purchase_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown purchase")
    return SealedLedgerEntryOut.model_validate(entry)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_api.py -q`
Expected: PASS (8).

- [ ] **Step 6: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (553 — 545 + 8).

- [ ] **Step 7: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/sealed/api_models.py backend/src/cardplatform/api.py backend/tests/test_sealed_ledger_api.py
git commit -m "feat(ledger): GET/POST/DELETE /sealed/ledger + valuate routes (Phase 05d T3)"
```

---

## Task 4: CLI — log / list / valuate

**Files:**
- Modify: `backend/src/cardplatform/cli.py` (three subparsers + handlers)
- Test: `backend/tests/test_cli_sealed_ledger.py`

Handlers open the DB via `db = Database(); db.create_all(); with db.session() as session:`
(mirror `find_deals` at `cli.py:222-265`). Handler signature `(args) -> int`. Prints via
`print(...)`, returns `0`. Subparsers use `set_defaults(handler=...)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_cli_sealed_ledger.py`:

```python
from cardplatform.cli import main
from cardplatform.config import Settings


def _settings(tmp_path, monkeypatch, **kw):
    s = Settings(data_dir=tmp_path, listings_api_key="app-id", sealed_sold_comp_limit=10, **kw)
    monkeypatch.setattr("cardplatform.cli.settings", s)
    monkeypatch.setattr("cardplatform.cli.Database", lambda: _DB(s))
    return s


class _DB:
    """Tiny stand-in so the CLI handler gets a fresh temp DB without touching data/."""

    def __init__(self, settings):
        from cardplatform.db.session import Database
        self._real = Database(settings)

    def create_all(self):
        self._real.create_all()

    @property
    def settings(self):
        return self._real.settings

    def session(self):
        return self._real.session()


def test_log_sealed_purchase_creates_and_prints(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main([
        "log-sealed-purchase", "--query", "scarlet violet booster box",
        "--quantity", "2", "--cost", "120",
    ])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "logged" in out
    assert "scarlet violet booster box" in out


def test_log_sealed_purchase_rejects_bad_cost(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main(["log-sealed-purchase", "--query", "box", "--cost", "-5"])
    # ValueError -> handler prints message + returns non-zero (do not crash).
    assert rc != 0
    assert "cost" in capsys.readouterr().out.lower()


def test_list_sealed_ledger_empty(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main(["list-sealed-ledger"])
    assert rc == 0
    assert "no purchases" in capsys.readouterr().out.lower()


def test_valuate_sealed_ledger_no_key(tmp_path, monkeypatch, capsys):
    s = Settings(data_dir=tmp_path, listings_api_key=None, sealed_sold_comp_limit=10)
    monkeypatch.setattr("cardplatform.cli.settings", s)
    monkeypatch.setattr("cardplatform.cli.Database", lambda: _DB(s))
    rc = main(["log-sealed-purchase", "--query", "box", "--cost", "10"])
    assert rc == 0
    rc = main(["valuate-sealed-ledger"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "set cardplatform_listings_api_key" in out
```

Note: `test_log_sealed_purchase_rejects_bad_cost` asserts the handler returns non-zero (not
a crash) on a `ValueError` — wrap the service call in try/except, print the message, return
`1`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_cli_sealed_ledger.py -q`
Expected: FAIL — unknown subcommand (`SystemExit(2)`) / handlers missing.

- [ ] **Step 3: Add the handlers + subparsers**

In `backend/src/cardplatform/cli.py`, add the handlers (near the other sealed handler
`find_sealed_deals`):

```python
def log_sealed_purchase(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        try:
            p = svc.create_purchase(
                query=args.query,
                product_type=args.type,
                quantity=args.quantity,
                cost_per_unit=args.cost,
                source=args.source,
                listing_url=args.url,
                notes=args.notes,
            )
        except ValueError as exc:
            print(f"Could not log purchase: {exc}")
            return 1
        print(f"Logged purchase #{p.id}: {p.quantity}× {p.query} @ ${p.cost_per_unit:.2f}/unit"
              f" (${p.quantity * p.cost_per_unit:.2f} total).")
    return 0


def list_sealed_ledger(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        entries = svc.list_ledger()
        if not entries:
            print("No purchases logged yet. Use 'log-sealed-purchase' to add one.")
            return 0
        key_set = bool(db.settings.listings_api_key)
        for e in entries:
            profit = "—" if e.profit is None else f"${e.profit:+.2f}"
            valued = f"${e.value_per_unit:.2f}/u (as of {e.market_fetched_at:%Y-%m-%d})" if e.valued else "not yet valued — run 'valuate-sealed-ledger'"
            print(f"#{e.id}  {e.quantity}× {e.query}  cost ${e.total_cost:.2f}  market {valued}  profit {profit}")
        if not key_set:
            print("\nSet CARDPLATFORM_LISTINGS_API_KEY to value purchases (fetch sold comps).")
    return 0


def valuate_sealed_ledger(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    if not db.settings.listings_api_key:
        print("No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY "
              "(eBay App ID) to value purchases.")
        return 0
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        if args.purchase_id is not None:
            v = svc.refresh_valuation(args.purchase_id)
            if v is None:
                print(f"No recent sold comps for purchase #{args.purchase_id} — no valuation recorded.")
            else:
                print(f"Valued purchase #{args.purchase_id} at ${v.value_per_unit:.2f}/unit "
                      f"(median of {v.comp_count} sold comps).")
            return 0
        result = svc.refresh_all()
        print(f"Valued {result.valued} purchase(s); {result.skipped_no_comps} had no sold comps.")
    return 0
```

Then register the subparsers (near the `find-sealed-deals` subparser, keeping
`set_defaults(handler=...)`):

```python
log_purchase = subparsers.add_parser(
    "log-sealed-purchase",
    help="Log a sealed product purchase to the ledger (Phase 05d).",
)
log_purchase.add_argument("--query", required=True, help="What you bought, e.g. 'scarlet violet booster box'")
log_purchase.add_argument("--quantity", type=int, default=1, help="Units bought (>=1).")
log_purchase.add_argument("--cost", type=float, required=True, help="Cost per unit in USD (>=0).")
log_purchase.add_argument("--type", default=None, help="booster_box|etb|pack|collection_box|other")
log_purchase.add_argument("--source", default=None, help="Where bought (eBay, local, etc.)")
log_purchase.add_argument("--url", default=None, help="Listing URL")
log_purchase.add_argument("--notes", default=None, help="Free-text notes")
log_purchase.set_defaults(handler=log_sealed_purchase)

list_ledger = subparsers.add_parser(
    "list-sealed-ledger",
    help="List the sealed purchase ledger with live profit (Phase 05d).",
)
list_ledger.set_defaults(handler=list_sealed_ledger)

valuate_ledger = subparsers.add_parser(
    "valuate-sealed-ledger",
    help="Refresh market valuations for sealed purchases (eBay sold comps, Phase 05d).",
)
valuate_ledger.add_argument("--purchase-id", type=int, default=None, help="Value one purchase; omit for all.")
valuate_ledger.set_defaults(handler=valuate_sealed_ledger)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_cli_sealed_ledger.py -q`
Expected: PASS (4).

- [ ] **Step 5: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (557 — 553 + 4).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/cli.py backend/tests/test_cli_sealed_ledger.py
git commit -m "feat(ledger): log/list/valuate-sealed-ledger CLI (Phase 05d T4)"
```

---

## Task 5: Frontend — SealedLedger component + 8th "Ledger" tab

**Files:**
- Modify: `frontend/src/api/types.ts` (ledger types)
- Modify: `frontend/src/api/client.ts` (getSealedLedger, logSealedPurchase, deleteSealedPurchase, valuateSealedLedger)
- Create: `frontend/src/components/SealedLedger.tsx`
- Modify: `frontend/src/components/AppShell.tsx` (8th tab + LedgerGlyph)
- Modify: `frontend/src/styles.css` (minimal `.ledger-*` rules; reuse `.deal-*`)
- Test: `frontend/src/__tests__/SealedLedger.test.tsx`
- Test: `frontend/src/__tests__/client.test.ts` (additions)

Mirrors `SealedDeals.tsx` (same imports, `useState` + `run`/load handlers, `.deals-toolbar` /
`.deal-*` classes, `formatMoney` from `../lib/format`, `relativeTime` from `../lib/time`,
honest-empty branches). `formatMoney(null)` → `—` (never `$0`).

- [ ] **Step 1: Add the wire types**

Append to `frontend/src/api/types.ts`:

```ts
export interface SealedLedgerEntry {
  id: number;
  query: string;
  product_type: string | null;
  quantity: number;
  cost_per_unit: number;
  total_cost: number;
  source: string | null;
  listing_url: string | null;
  notes: string | null;
  bought_at: string;
  created_at: string;
  value_per_unit: number | null;
  total_current_value: number | null;
  profit: number | null;
  profit_pct: number | null;
  market_fetched_at: string | null;
  market_source: string | null;
  valued: boolean;
}

export interface SealedLedgerResponse {
  purchases: SealedLedgerEntry[];
  listings_unavailable: boolean;
}

export interface ValuationRefreshResult {
  valued: number;
  skipped_no_comps: number;
  skipped_no_key: boolean;
}
```

- [ ] **Step 2: Add the API client helpers**

Append to `frontend/src/api/client.ts` (mirror `getSealedDeals` for GET + `addToCollection`
for POST JSON + `removeFromCollection` for DELETE):

```ts
export async function getSealedLedger(): Promise<SealedLedgerResponse> {
  return expectJsonOrDetail<SealedLedgerResponse>(await fetch(`${BASE}/sealed/ledger`));
}

export async function logSealedPurchase(body: {
  query: string;
  quantity?: number;
  cost_per_unit: number;
  product_type?: string | null;
  source?: string | null;
  listing_url?: string | null;
  notes?: string | null;
}): Promise<SealedPurchaseOut> {
  const response = await fetch(`${BASE}/sealed/ledger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json();
}

export async function deleteSealedPurchase(purchaseId: number): Promise<void> {
  const response = await fetch(`${BASE}/sealed/ledger/${purchaseId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
}

export async function valuateSealedLedger(): Promise<ValuationRefreshResult> {
  return expectJsonOrDetail<ValuationRefreshResult>(
    await fetch(`${BASE}/sealed/ledger/valuate`, { method: "POST" }),
  );
}
```

Add `SealedLedgerResponse`, `SealedPurchaseOut`, `ValuationRefreshResult` to the existing
`import type { ... } from "./types"` in `client.ts` (only the new ones; don't duplicate).
Note: `SealedPurchaseOut` must also be added to `types.ts`:

```ts
export interface SealedPurchaseOut {
  id: number;
  query: string;
  product_type: string | null;
  quantity: number;
  cost_per_unit: number;
  source: string | null;
  listing_url: string | null;
  notes: string | null;
  bought_at: string;
  created_at: string;
}
```

- [ ] **Step 3: Write the failing component tests**

`frontend/src/__tests__/SealedLedger.test.tsx` (mirror `SealedDeals.test.tsx` `stubFetch`
routed by URL substring + `container.querySelector`):

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import SealedLedger from "../components/SealedLedger";
import type { SealedLedgerResponse, ValuationRefreshResult } from "../api/types";

function baseEntry(over: Partial<SealedLedgerResponse["purchases"][number]> = {}) {
  return {
    id: 1,
    query: "scarlet violet booster box",
    product_type: "booster_box",
    quantity: 2,
    cost_per_unit: 120,
    total_cost: 240,
    source: "eBay",
    listing_url: null,
    notes: null,
    bought_at: "2026-08-19T00:00:00Z",
    created_at: "2026-08-19T00:00:00Z",
    value_per_unit: 150,
    total_current_value: 300,
    profit: 60,
    profit_pct: 0.25,
    market_fetched_at: "2026-08-19T12:00:00Z",
    market_source: "ebay_sold_median",
    valued: true,
    ...over,
  };
}

function stubFetch(opts: {
  ledger?: SealedLedgerResponse;
  refresh?: ValuationRefreshResult;
  logStatus?: number;
  deleteStatus?: number;
} = {}) {
  const ledger: SealedLedgerResponse = opts.ledger ?? {
    purchases: [baseEntry()],
    listings_unavailable: false,
  };
  const refresh: ValuationRefreshResult = opts.refresh ?? {
    valued: 1, skipped_no_comps: 0, skipped_no_key: false,
  };
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/sealed/ledger/valuate") && method === "POST") {
      return { ok: true, status: 200, json: async () => refresh };
    }
    if (u.match(/\/sealed\/ledger\/\d+$/) && method === "DELETE") {
      return { ok: (opts.deleteStatus ?? 204) < 400, status: opts.deleteStatus ?? 204, json: async () => ({}) };
    }
    if (u.endsWith("/sealed/ledger") && method === "POST") {
      return { ok: (opts.logStatus ?? 201) < 400, status: opts.logStatus ?? 201, json: async () => ({ id: 99 }) };
    }
    if (u.endsWith("/sealed/ledger")) {
      return { ok: true, status: 200, json: async () => ledger };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

describe("SealedLedger", () => {
  it("renders ledger entries with profit and never $0.00 for unvalued", async () => {
    stubFetch({
      ledger: { purchases: [baseEntry({ valued: false, value_per_unit: null, total_current_value: null, profit: null, profit_pct: null, market_fetched_at: null, market_source: null })], listings_unavailable: false },
    });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    expect(container.textContent).not.toMatch(/\$0\.00/);
    expect(container.textContent).toMatch(/not yet valued/i);
  });

  it("shows an honest empty state when there are no purchases", async () => {
    stubFetch({ ledger: { purchases: [], listings_unavailable: false } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.textContent).toMatch(/no purchases logged/i));
  });

  it("warns when the eBay key is missing on refresh", async () => {
    stubFetch({
      ledger: { purchases: [baseEntry()], listings_unavailable: true },
      refresh: { valued: 0, skipped_no_comps: 0, skipped_no_key: true },
    });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const refreshBtn = [...container.querySelectorAll("button")].find((b) => /refresh/i.test(b.textContent || "")) as HTMLButtonElement;
    expect(refreshBtn).toBeTruthy();
    fireEvent.click(refreshBtn);
    await waitFor(() => expect(container.textContent).toMatch(/set cardplatform_listings_api_key/i));
  });

  it("logs a purchase via the form", async () => {
    const spy = stubFetch();
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const queryInput = container.querySelector('input[name="ledger-query"]') as HTMLInputElement;
    const costInput = container.querySelector('input[name="ledger-cost"]') as HTMLInputElement;
    fireEvent.change(queryInput, { target: { value: "151 booster bundle" } });
    fireEvent.change(costInput, { target: { value: "27.50" } });
    const logBtn = [...container.querySelectorAll("button")].find((b) => /log purchase/i.test(b.textContent || "")) as HTMLButtonElement;
    fireEvent.click(logBtn);
    await waitFor(() => {
      const post = spy.mock.calls.find((c) => (c[1]?.method === "POST") && String(c[0]).endsWith("/sealed/ledger"));
      expect(post).toBeTruthy();
    });
  });

  it("deletes a purchase", async () => {
    const spy = stubFetch();
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const delBtn = container.querySelector(".ledger-delete") as HTMLButtonElement;
    expect(delBtn).toBeTruthy();
    fireEvent.click(delBtn);
    await waitFor(() => {
      const del = spy.mock.calls.find((c) => c[1]?.method === "DELETE");
      expect(del).toBeTruthy();
    });
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `npm --prefix frontend test -- --run SealedLedger`
Expected: FAIL — component does not exist.

- [ ] **Step 5: Implement the component**

`frontend/src/components/SealedLedger.tsx`:

```tsx
import { useEffect, useState } from "react";
import {
  deleteSealedPurchase,
  getSealedLedger,
  logSealedPurchase,
  valuateSealedLedger,
} from "../api/client";
import type { SealedLedgerEntry, SealedLedgerResponse } from "../api/types";
import { formatMoney } from "../lib/format";
import { relativeTime } from "../lib/time";

export default function SealedLedger() {
  const [data, setData] = useState<SealedLedgerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // log form
  const [query, setQuery] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [cost, setCost] = useState("");
  const [ptype, setPtype] = useState("");
  const [source, setSource] = useState("");
  const [logging, setLogging] = useState(false);

  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true); setError(null);
    try { setData(await getSealedLedger()); }
    catch (e) { setError(e instanceof Error ? e.message : "Couldn't load the ledger."); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function logPurchase(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    const c = parseFloat(cost);
    const n = parseInt(quantity, 10);
    if (q.length < 2 || !Number.isFinite(c) || c < 0 || !Number.isFinite(n) || n < 1) {
      setError("Enter a product, a cost per unit (>=0), and a quantity (>=1).");
      return;
    }
    setLogging(true); setError(null); setNotice(null);
    try {
      await logSealedPurchase({ query: q, quantity: n, cost_per_unit: c, product_type: ptype || null, source: source || null });
      setQuery(""); setCost(""); setQuantity("1"); setPtype(""); setSource("");
      setNotice("Purchase logged.");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Couldn't log the purchase."); }
    finally { setLogging(false); }
  }

  async function refresh() {
    setRefreshing(true); setError(null); setNotice(null);
    try {
      const res = await valuateSealedLedger();
      if (res.skipped_no_key) {
        setNotice("Set CARDPLATFORM_LISTINGS_API_KEY to value purchases (fetch sold comps).");
      } else {
        setNotice(`Valued ${res.valued} purchase(s); ${res.skipped_no_comps} had no sold comps.`);
      }
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Couldn't refresh valuations."); }
    finally { setRefreshing(false); }
  }

  async function remove(id: number) {
    try { await deleteSealedPurchase(id); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Couldn't delete the purchase."); }
  }

  return (
    <section className="deals">
      <p className="muted small">Log sealed boxes/packs you bought; track live profit vs the eBay sold-comps median.</p>

      <form className="ledger-form" onSubmit={logPurchase}>
        <input name="ledger-query" className="deals-search" placeholder="Product, e.g. 'scarlet violet booster box'" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Product" autoComplete="off" />
        <input name="ledger-cost" className="ledger-input" type="number" step="0.01" min="0" placeholder="Cost/unit $" value={cost} onChange={(e) => setCost(e.target.value)} aria-label="Cost per unit" />
        <input name="ledger-qty" className="ledger-input" type="number" min="1" step="1" placeholder="Qty" value={quantity} onChange={(e) => setQuantity(e.target.value)} aria-label="Quantity" />
        <select name="ledger-type" className="ledger-input" value={ptype} onChange={(e) => setPtype(e.target.value)} aria-label="Product type">
          <option value="">Type…</option>
          <option value="booster_box">Booster box</option>
          <option value="etb">ETB</option>
          <option value="pack">Pack</option>
          <option value="collection_box">Collection box</option>
          <option value="other">Other</option>
        </select>
        <input name="ledger-source" className="ledger-input" placeholder="Bought from (optional)" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source" autoComplete="off" />
        <button type="submit" className="sealed-deals-btn" disabled={logging}>{logging ? "Logging…" : "Log purchase"}</button>
      </form>

      <div className="deals-toolbar">
        <button type="button" className="sealed-deals-btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh valuations"}
        </button>
      </div>

      {notice && <p className="muted small">{notice}</p>}
      {error && <p className="error">{error}</p>}
      {loading && <div className="skeleton skeleton-block" aria-label="Loading ledger" />}
      {data && <LedgerBody entries={data.purchases} onRemove={remove} />}
    </section>
  );
}

function LedgerBody({ entries, onRemove }: { entries: SealedLedgerEntry[]; onRemove: (id: number) => void }) {
  if (entries.length === 0) {
    return <p className="muted">No purchases logged yet — log one above.</p>;
  }
  return (
    <ul className="deal-list">
      {entries.map((e) => {
        const profitClass = e.profit === null ? "" : e.profit >= 0 ? "ledger-profit pos" : "ledger-profit neg";
        return (
          <li className="deal-card" key={e.id}>
            <div className="deal-card-head">
              <span className="deal-title">{e.quantity}× {e.query}</span>
              <span className="deal-price">{formatMoney(e.total_current_value)}</span>
            </div>
            <div className="deal-card-meta">
              <div className="deal-row"><span className="deal-row-label">Cost</span><span className="deal-row-value">{formatMoney(e.total_cost)} ({formatMoney(e.cost_per_unit)}/u)</span></div>
              <div className="deal-row"><span className="deal-row-label">Market</span><span className="deal-row-value">{e.valued ? `${formatMoney(e.value_per_unit)}/u` : "not yet valued — click Refresh"}</span></div>
              <div className="deal-row"><span className="deal-row-label">Profit</span><span className={`deal-row-value ${profitClass}`}>{e.profit === null ? "—" : `${formatMoney(e.profit)} (${e.profit_pct === null ? "—" : (e.profit_pct * 100).toFixed(0) + "%"})`}</span></div>
              {e.valued && e.market_fetched_at && (
                <div className="deal-row"><span className="deal-row-label">Valued</span><span className="deal-row-value">{relativeTime(e.market_fetched_at)} · {e.market_source}</span></div>
              )}
              {e.source && <div className="deal-row"><span className="deal-row-label">Bought from</span><span className="deal-row-value">{e.source}</span></div>}
              {e.notes && <div className="deal-row"><span className="deal-row-label">Notes</span><span className="deal-row-value">{e.notes}</span></div>}
            </div>
            <div className="deal-chips">
              <span className="deal-caveat">Gross edge — selling fees not subtracted; profit is indicative (as of valuation).</span>
              <button type="button" className="ledger-delete" onClick={() => onRemove(e.id)}>Delete</button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 6: Add the 8th tab to AppShell**

In `frontend/src/components/AppShell.tsx`:

1. Extend the `TabView` union (add `ledger`):
```tsx
type TabView = "scan" | "vault" | "alerts" | "deals" | "sealed" | "ledger" | "browse" | "more";
```
2. Add to `TAB_TITLES`:
```tsx
  ledger: "Ledger",
```
3. Add the import:
```tsx
import SealedLedger from "./SealedLedger";
```
4. Add a render branch (mirror the `view === "sealed" ? <SealedDeals />` line):
```tsx
) : view === "ledger" ? (
  <SealedLedger />
) : view === "sealed" ? (
```
(Insert the `ledger` branch immediately before the `sealed` branch.)
5. Add a `TabButton` in the bottom nav (mirror the Sealed `TabButton`, place it after the Sealed button):
```tsx
<TabButton
  label="Ledger"
  active={view === "ledger" && !selectedCard}
  onClick={() => selectTab("ledger")}
  glyph={<LedgerGlyph />}
/>
```
6. Add the `LedgerGlyph` (mirror `BoxGlyph` — stroke-based, `currentColor`, 24×24 viewBox):
```tsx
function LedgerGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 7h8M8 11h8M8 15h5" />
    </svg>
  );
}
```

- [ ] **Step 7: Add minimal ledger CSS**

Append to `frontend/src/styles.css` (reuse `.deal-*` / `.deals-toolbar` / `.deals-search`
verbatim; only add these):

```css
.ledger-form { display: grid; grid-template-columns: 1fr repeat(4, minmax(0, 1fr)) auto; gap: var(--sp-2); align-items: center; }
.ledger-form .deals-search { grid-column: 1 / span 1; }
.ledger-input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; min-width: 0; }
.ledger-profit.pos { color: #2e7d32; }
.ledger-profit.neg { color: #c62828; }
.ledger-delete { background: transparent; border: 1px solid var(--line); border-radius: 8px; color: var(--text); padding: 4px 10px; cursor: pointer; font: inherit; }
.ledger-delete:hover { border-color: var(--accent); }
@media (max-width: 720px) {
  .ledger-form { grid-template-columns: 1fr 1fr; }
  .ledger-form .deals-search { grid-column: 1 / span 2; }
}
```

- [ ] **Step 8: Run the component tests**

Run: `npm --prefix frontend test -- --run SealedLedger`
Expected: PASS (5).

- [ ] **Step 9: Add client tests**

Append to `frontend/src/__tests__/client.test.ts` (mirror the `getSealedDeals` tests using
`mockFetch`):

```ts
describe("sealed ledger client", () => {
  it("getSealedLedger hits /api/sealed/ledger", async () => {
    const spy = mockFetch(200, { purchases: [], listings_unavailable: false });
    vi.stubGlobal("fetch", spy);
    await getSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger");
    vi.unstubAllGlobals();
  });

  it("logSealedPurchase POSTs JSON to /api/sealed/ledger", async () => {
    const spy = mockFetch(201, { id: 1, query: "x", product_type: null, quantity: 1, cost_per_unit: 1, source: null, listing_url: null, notes: null, bought_at: "", created_at: "" });
    vi.stubGlobal("fetch", spy);
    await logSealedPurchase({ query: "box", cost_per_unit: 10 });
    const call = spy.mock.calls[0];
    expect(String(call[0])).toContain("/api/sealed/ledger");
    expect(call[1]?.method).toBe("POST");
    expect(JSON.parse(call[1]?.body as string).query).toBe("box");
    vi.unstubAllGlobals();
  });

  it("valuateSealedLedger POSTs /api/sealed/ledger/valuate", async () => {
    const spy = mockFetch(200, { valued: 1, skipped_no_comps: 0, skipped_no_key: false });
    vi.stubGlobal("fetch", spy);
    await valuateSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger/valuate");
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    vi.unstubAllGlobals();
  });
});
```

Add `getSealedLedger`, `logSealedPurchase`, `valuateSealedLedger` to the test file's import
from `../api/client` if not already present.

- [ ] **Step 10: Run the full frontend suite + build**

Run: `npm --prefix frontend test -- --run`
Expected: PASS (128 — 115 + 5 component + 3 client, adjust to actual).

Run: `npm --prefix frontend run build`
Expected: clean build (tsc + vite).

- [ ] **Step 11: Commit**

```bash
cd C:\ClaudeKnowledge
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/SealedLedger.tsx frontend/src/components/AppShell.tsx frontend/src/styles.css frontend/src/__tests__/SealedLedger.test.tsx frontend/src/__tests__/client.test.ts
git commit -m "feat(ledger): SealedLedger component + 8th 'Ledger' tab (Phase 05d T5)"
```

---

## Task 6: Google deps + config + OAuth client (credential lifecycle)

**Files:**
- Modify: `backend/pyproject.toml` (add two deps)
- Modify: `backend/src/cardplatform/config.py` (google_* settings)
- Create: `backend/src/cardplatform/sealed/sheets.py` (GoogleSheetsClient — credentials only)
- Test: `backend/tests/test_google_sheets_client.py`

**Install the new deps into the venv (NOT system Python 3.14):**
`backend/.venv/Scripts/python -m pip install "google-auth-oauthlib>=1.2" "google-api-python-client>=2.100"`
Then add the same two lines to `pyproject.toml` so the lockfile/declared deps match.

OAuth uses `google-auth-oauthlib` `InstalledAppFlow` (browser sign-in) +
`google.oauth2.credentials.Credentials` (token load/save/refresh). The sync *write* comes in
T7; this task lands credential management + `is_configured()` + tests (all mocked — no
network, no browser).

- [ ] **Step 1: Add deps + install**

Edit `backend/pyproject.toml` `dependencies` list — after `"pywebpush>=2.0",`:

```toml
    # Phase 05d: Google Sheets sync (OAuth browser sign-in + Sheets v4 write).
    "google-auth-oauthlib>=1.2",
    "google-api-python-client>=2.100",
```

Install into the venv:
`backend/.venv/Scripts/python -m pip install "google-auth-oauthlib>=1.2" "google-api-python-client>=2.100"`

- [ ] **Step 2: Add config fields**

In `backend/src/cardplatform/config.py`, add two fields to `Settings` (near the sealed_*
fields):

```python
    # Phase 05d — Google Sheets sync (OAuth browser sign-in; local-first, opt-in).
    google_sheet_id: str | None = Field(default=None)
    google_sheet_tab: str = Field(default="Sealed Ledger")
```

And add two properties (mirror the `db_path` property pattern):

```python
    @property
    def google_client_secret_path(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def google_token_path(self) -> Path:
        return self.data_dir / "google_token.json"
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/test_google_sheets_client.py`:

```python
import json

import pytest

from cardplatform.config import Settings
from cardplatform.sealed.sheets import GoogleSheetsClient


def _settings(tmp_path, sheet_id="SHEET123"):
    return Settings(data_dir=tmp_path, google_sheet_id=sheet_id, google_sheet_tab="Sealed Ledger")


def _write_secret(path):
    path.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))


def test_not_configured_without_secret(tmp_path):
    s = _settings(tmp_path)
    client = GoogleSheetsClient(s)
    assert client.is_configured() is False


def test_not_configured_without_sheet_id(tmp_path):
    s = _settings(tmp_path, sheet_id=None)
    _write_secret(s.google_client_secret_path)
    assert GoogleSheetsClient(s).is_configured() is False


def test_configured_with_secret_and_sheet_id(tmp_path):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    assert GoogleSheetsClient(s).is_configured() is True


def test_authorize_runs_flow_when_no_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    client = GoogleSheetsClient(s)

    captured = {}

    class FakeCreds:
        def __init__(self, valid=True, expired=False, refresh_token="rt"):
            self.valid = valid
            self.expired = expired
            self.refresh_token = refresh_token

        def to_json(self):
            return json.dumps({"token": "abc", "refresh_token": self.refresh_token})

    class FakeFlow:
        def __init__(self, *a, **kw):
            captured["flow_built"] = True

        def run_local_server(self, port=0):
            captured["ran_browser"] = True
            return FakeCreds()

    def fake_from_file(path, scopes):
        raise FileNotFoundError(path)  # no token yet

    monkeypatch.setattr("cardplatform.sealed.sheets.InstalledAppFlow.from_client_secrets_file", lambda *a, **kw: FakeFlow())
    monkeypatch.setattr("cardplatform.sealed.sheets.Credentials.from_authorized_user_file", fake_from_file)

    creds = client._authorize()
    assert captured["ran_browser"] is True
    assert s.google_token_path.exists()  # token persisted
    assert json.loads(s.google_token_path.read_text())["token"] == "abc"


def test_authorize_loads_existing_valid_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)

    class FakeCreds:
        valid = True
        expired = False
        refresh_token = "rt"

        def to_json(self):
            return json.dumps({"token": "existing"})

    s.google_token_path.write_text(json.dumps({"token": "existing"}))
    monkeypatch.setattr(
        "cardplatform.sealed.sheets.Credentials.from_authorized_user_file",
        lambda path, scopes: FakeCreds(),
    )
    client = GoogleSheetsClient(s)
    creds = client._authorize()
    assert creds.valid is True
    # No browser flow should have run; token file unchanged.
    assert json.loads(s.google_token_path.read_text())["token"] == "existing"


def test_authorize_refreshes_expired_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    s.google_token_path.write_text(json.dumps({"token": "old"}))

    refreshed = {"called": False}

    class FakeCreds:
        valid = False
        expired = True
        refresh_token = "rt"

        def refresh(self, req):
            refreshed["called"] = True
            self.valid = True
            self.expired = False

        def to_json(self):
            return json.dumps({"token": "refreshed"})

    monkeypatch.setattr("cardplatform.sealed.sheets.Credentials.from_authorized_user_file", lambda path, scopes: FakeCreds())
    client = GoogleSheetsClient(s)
    creds = client._authorize()
    assert refreshed["called"] is True
    assert creds.valid is True
    assert json.loads(s.google_token_path.read_text())["token"] == "refreshed"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_google_sheets_client.py -q`
Expected: FAIL — `ImportError: cannot import name 'GoogleSheetsClient'`.

- [ ] **Step 5: Implement the OAuth client**

`backend/src/cardplatform/sealed/sheets.py`:

```python
"""Google Sheets sync client (OAuth browser sign-in).

Local-first, opt-in: the sealed ledger is the source of truth; Sheets is a mirror. This
module handles credential lifecycle (load/refresh/authorize via InstalledAppFlow) + an
`is_configured()` honest-empty gate. The sync *write* lives here too (added in T7).

Token + client secret are stored under data/ (gitignored) — never committed. The OAuth flow
opens the user's browser (flow.run_local_server) — this is a local-first desktop app, not a
headless server.
"""

from __future__ import annotations

from pathlib import Path

from cardplatform.config import Settings, default_settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    @property
    def secret_path(self) -> Path:
        return self.settings.google_client_secret_path

    @property
    def token_path(self) -> Path:
        return self.settings.google_token_path

    def is_configured(self) -> bool:
        """True iff a client secret file exists AND a spreadsheet id is set. No network call."""
        return bool(self.settings.google_sheet_id) and self.secret_path.exists()

    def _authorize(self):
        # Imported lazily so the module imports cleanly when google libs are absent or in
        # tests that monkeypatch these symbols.
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.secret_path), SCOPES)
                creds = flow.run_local_server(port=0)
            self.token_path.write_text(creds.to_json())
        return creds
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_google_sheets_client.py -q`
Expected: PASS (6).

- [ ] **Step 7: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (563 — 557 + 6).

- [ ] **Step 8: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/pyproject.toml backend/src/cardplatform/config.py backend/src/cardplatform/sealed/sheets.py backend/tests/test_google_sheets_client.py
git commit -m "feat(ledger): Google OAuth client + google_* settings (Phase 05d T6)"
```

---

## Task 7: Sheets sync write + API route + CLI + row builder

**Files:**
- Modify: `backend/src/cardplatform/sealed/sheets.py` (add `sync` + `SheetsSyncResult`)
- Modify: `backend/src/cardplatform/sealed/ledger.py` (add `build_sheet_rows`)
- Modify: `backend/src/cardplatform/api.py` (`POST /sealed/ledger/sync`)
- Modify: `backend/src/cardplatform/cli.py` (`sync-sealed-ledger`)
- Test: `backend/tests/test_google_sheets_client.py` (sync additions)
- Test: `backend/tests/test_sealed_ledger_sync_api.py`
- Test: `backend/tests/test_sealed_ledger_service.py` (build_sheet_rows additions)

Sync = full-tab overwrite (clear + write header + rows) — idempotent, reflects edits/deletes.
Honest: not configured → `synced=False, reason="not_configured"`, no network, no raise.

- [ ] **Step 1: Add `SheetsSyncResult` + `sync` to the client**

Append to `backend/src/cardplatform/sealed/sheets.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class SheetsSyncResult:
    synced: bool
    rows: int
    reason: str | None = None
```

Add the method to `GoogleSheetsClient`:

```python
    def sync(self, rows: list[list[str]]) -> SheetsSyncResult:
        """Full-tab overwrite: clear the tab range, then write header + rows. Idempotent.
        Returns SheetsSyncResult(synced=False, reason='not_configured') without a network
        call when OAuth/sheet aren't configured — never raises for that case."""
        if not self.is_configured():
            return SheetsSyncResult(synced=False, rows=0, reason="not_configured")
        from googleapiclient.discovery import build

        creds = self._authorize()
        service = build("sheets", "v4", credentials=creds)
        tab = self.settings.google_sheet_tab
        spreadsheet_id = self.settings.google_sheet_id
        # Clear first so the sheet mirrors the current truth (edits/deletes included).
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"{tab}!A1:Z10000"
        ).execute()
        body = {"values": rows}
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body=body,
        ).execute()
        return SheetsSyncResult(synced=True, rows=max(0, len(rows) - 1))  # exclude header
```

- [ ] **Step 2: Add `build_sheet_rows` to the ledger service**

Append to `backend/src/cardplatform/sealed/ledger.py` (a pure function — no DB, no network;
formats entries into sheet rows with nulls → ""):

```python
def build_sheet_rows(entries: list[LedgerEntry]) -> list[list[str]]:
    """Pure: ledger entries -> sheet rows (header first). Nulls -> "" (the sheet shows
    blanks, not $0). Mirrors the frontend's honest-empty stance."""
    header = [
        "Date", "Product", "Type", "Qty", "Cost/Unit", "Total Cost",
        "Market/Unit", "Total Value", "Profit", "Profit %",
        "Valued At", "Source", "Bought From", "Notes",
    ]

    def _money(v: float | None) -> str:
        return "" if v is None else f"{v:.2f}"

    def _pct(v: float | None) -> str:
        return "" if v is None else f"{v * 100:.0f}%"

    rows = [header]
    for e in entries:
        rows.append([
            e.bought_at.strftime("%Y-%m-%d") if e.bought_at else "",
            e.query,
            e.product_type or "",
            str(e.quantity),
            _money(e.cost_per_unit),
            _money(e.total_cost),
            _money(e.value_per_unit),
            _money(e.total_current_value),
            _money(e.profit),
            _pct(e.profit_pct),
            e.market_fetched_at.strftime("%Y-%m-%d %H:%M") if e.market_fetched_at else "",
            e.market_source or "",
            e.source or "",
            e.notes or "",
        ])
    return rows
```

- [ ] **Step 3: Write the failing tests**

Add to `backend/tests/test_sealed_ledger_service.py`:

```python
from cardplatform.sealed.ledger import build_sheet_rows


def test_build_sheet_rows_header_and_nulls_to_blank(db):
    svc = _service(db)
    svc.create_purchase(query="box", quantity=1, cost_per_unit=100.0)  # unvalued
    rows = build_sheet_rows(svc.list_ledger())
    assert rows[0][0] == "Date"
    assert rows[0][7] == "Total Value"
    row = rows[1]
    assert row[1] == "box"
    assert row[6] == ""   # market/unit blank (unvalued)
    assert row[8] == ""   # profit blank
    assert row[9] == ""   # profit % blank
    assert row[5] == "100.00"  # total cost known


def test_build_sheet_rows_valued_entry_filled(db):
    svc = _service(db)
    p = svc.create_purchase(query="box", quantity=2, cost_per_unit=100.0)
    db.add(SealedValuation(purchase_id=p.id, value_per_unit=150.0, comp_count=4))
    db.commit()
    rows = build_sheet_rows(svc.list_ledger())
    row = rows[1]
    assert row[6] == "150.00"  # market/unit
    assert row[7] == "300.00"  # total value
    assert row[8] == "100.00"  # profit
    assert row[9] == "50%"     # profit %
```

`backend/tests/test_sealed_ledger_sync_api.py`:

```python
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings


def _client(monkeypatch, db, sheet_id="SHEET123"):
    app = create_app()
    monkeypatch.setattr(
        "cardplatform.api.settings",
        Settings(listings_api_key="app-id", google_sheet_id=sheet_id, google_sheet_tab="Sealed Ledger"),
    )

    def _override_session():
        yield db

    app.dependency_overrides[get_session] = _override_session
    return TestClient(app)


def test_sync_not_configured_returns_honest_result(db, monkeypatch):
    # No sheet id -> not configured (even though we don't write a secret file here).
    client = _client(monkeypatch, db, sheet_id=None)
    r = client.post("/api/sealed/ledger/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is False
    assert body["reason"] == "not_configured"


def test_sync_configured_writes_rows(db, monkeypatch):
    client = _client(monkeypatch, db, sheet_id="SHEET123")
    # Log a purchase so the sheet has one row.
    client.post("/api/sealed/ledger", json={"query": "box", "cost_per_unit": 10.0})

    calls = {"clear": False, "update_body": None}

    class FakeValues:
        def clear(self, spreadsheetId, range):
            calls["clear"] = True
            return self

        def update(self, spreadsheetId, range, valueInputOption, body):
            calls["update_body"] = body
            return self

        def execute(self):
            return {}

    class FakeSpreadsheets:
        def values(self):
            return FakeValues()

    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    # Patch is_configured -> True (secret file absent in tmp; route constructs its own client
    # on the module settings, so patch the client class used by the route).
    monkeypatch.setattr("cardplatform.sealed.sheets.GoogleSheetsClient.is_configured", lambda self: True)
    monkeypatch.setattr("cardplatform.sealed.sheets.GoogleSheetsClient._authorize", lambda self: object())
    import cardplatform.sealed.sheets as sheets_mod
    monkeypatch.setattr(sheets_mod, "build", lambda *a, **k: FakeService(), raising=False)
    # `build` is imported inside sync(); patch it in the googleapiclient.discovery namespace.
    import googleapiclient.discovery as discovery
    monkeypatch.setattr(discovery, "build", lambda *a, **k: FakeService())

    r = client.post("/api/sealed/ledger/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is True
    assert body["rows"] == 1  # one purchase row (header excluded)
    assert calls["clear"] is True
    assert calls["update_body"]["values"][0][0] == "Date"  # header
    assert calls["update_body"]["values"][1][1] == "box"
```

Add to `backend/tests/test_google_sheets_client.py` (sync-not-configured):

```python
def test_sync_not_configured_returns_honest(tmp_path):
    s = _settings(tmp_path)  # no secret file written
    client = GoogleSheetsClient(s)
    result = client.sync([["Date"], ["row1"]])
    assert result.synced is False
    assert result.reason == "not_configured"
    assert result.rows == 0
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_sync_api.py backend/tests/test_google_sheets_client.py backend/tests/test_sealed_ledger_service.py -q`
Expected: FAIL — `sync` missing / route missing / `build_sheet_rows` missing.

- [ ] **Step 5: Add the API sync route**

In `backend/src/cardplatform/api.py`, add to the sealed api_models import (already added in
T3): `SheetsSyncResultOut` is already imported. Add the route after the `/sealed/ledger/...`
routes:

```python
@app.post("/sealed/ledger/sync", response_model=SheetsSyncResultOut)
def sync_sealed_ledger(session: Session = Depends(get_session)) -> SheetsSyncResultOut:
    from cardplatform.sealed.ledger import build_sheet_rows
    from cardplatform.sealed.sheets import GoogleSheetsClient

    provider = EbayListingsProvider(settings)
    svc = LedgerService(session, provider=provider, settings=settings)
    rows = build_sheet_rows(svc.list_ledger())
    result = GoogleSheetsClient(settings).sync(rows)
    return SheetsSyncResultOut(synced=result.synced, rows=result.rows, reason=result.reason)
```

- [ ] **Step 6: Add the CLI sync command**

In `backend/src/cardplatform/cli.py`:

```python
def sync_sealed_ledger(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService, build_sheet_rows
    from cardplatform.sealed.sheets import GoogleSheetsClient
    db = Database()
    db.create_all()
    client = GoogleSheetsClient(db.settings)
    if not client.is_configured():
        print("Google Sheets sync not configured. To enable:")
        print("  1. Create a Google Cloud OAuth 2.0 Client ID (Desktop app) and download the")
        print("     JSON as: data/credentials.json")
        print("  2. Create a (possibly empty) Google Sheet and set its ID (from the URL) in")
        print("     CARDPLATFORM_GOOGLE_SHEET_ID (optional tab: CARDPLATFORM_GOOGLE_SHEET_TAB,")
        print("     default 'Sealed Ledger').")
        print("  3. Run 'sync-sealed-ledger' once to sign in (browser) and save a token.")
        return 0
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        rows = build_sheet_rows(svc.list_ledger())
    result = client.sync(rows)
    if not result.synced:
        print(f"Sync did not complete: {result.reason}.")
        return 1
    print(f"Synced {result.rows} purchase row(s) to Google Sheet '{db.settings.google_sheet_tab}'.")
    return 0
```

Register the subparser:

```python
sync_ledger = subparsers.add_parser(
    "sync-sealed-ledger",
    help="Sync the sealed ledger to a Google Sheet (OAuth, Phase 05d).",
)
sync_ledger.set_defaults(handler=sync_sealed_ledger)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sealed_ledger_sync_api.py backend/tests/test_google_sheets_client.py backend/tests/test_sealed_ledger_service.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (571 — 563 + 2 service + 1 sync-not-configured + 2 sync-api + adjust).

- [ ] **Step 9: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/sealed/sheets.py backend/src/cardplatform/sealed/ledger.py backend/src/cardplatform/api.py backend/src/cardplatform/cli.py backend/tests/test_google_sheets_client.py backend/tests/test_sealed_ledger_sync_api.py backend/tests/test_sealed_ledger_service.py
git commit -m "feat(ledger): Google Sheets sync write + /sealed/ledger/sync + CLI (Phase 05d T7)"
```

---

## Task 8: Frontend — Sync to Google Sheets button

**Files:**
- Modify: `frontend/src/api/types.ts` (`SheetsSyncResult`)
- Modify: `frontend/src/api/client.ts` (`syncSealedLedger`)
- Modify: `frontend/src/components/SealedLedger.tsx` (sync button + state)
- Test: `frontend/src/__tests__/SealedLedger.test.tsx` (sync cases)
- Test: `frontend/src/__tests__/client.test.ts` (`syncSealedLedger`)

- [ ] **Step 1: Add the type + client helper**

`frontend/src/api/types.ts`:

```ts
export interface SheetsSyncResult {
  synced: boolean;
  rows: number;
  reason: string | null;
}
```

`frontend/src/api/client.ts`:

```ts
export async function syncSealedLedger(): Promise<SheetsSyncResult> {
  return expectJsonOrDetail<SheetsSyncResult>(
    await fetch(`${BASE}/sealed/ledger/sync`, { method: "POST" }),
  );
}
```

Add `SheetsSyncResult` to the types import in `client.ts`.

- [ ] **Step 2: Write the failing tests**

Add to `frontend/src/__tests__/SealedLedger.test.tsx` — extend `stubFetch` to handle
`/sealed/ledger/sync`. Update the `stubFetch` signature:

```tsx
function stubFetch(opts: {
  ledger?: SealedLedgerResponse;
  refresh?: ValuationRefreshResult;
  sync?: SheetsSyncResult;
  logStatus?: number;
  deleteStatus?: number;
} = {}) {
  const sync: SheetsSyncResult = opts.sync ?? { synced: true, rows: 1, reason: null };
  // ...inside the spy, add before the final fallback:
    if (u.endsWith("/sealed/ledger/sync") && (init?.method === "POST")) {
      return { ok: true, status: 200, json: async () => sync };
    }
```

Add `SheetsSyncResult` to the test's type import. Then add two tests:

```tsx
  it("syncs to Google Sheets and reports rows", async () => {
    stubFetch({ sync: { synced: true, rows: 2, reason: null } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const syncBtn = [...container.querySelectorAll("button")].find((b) => /sync to google/i.test(b.textContent || "")) as HTMLButtonElement;
    expect(syncBtn).toBeTruthy();
    fireEvent.click(syncBtn);
    await waitFor(() => expect(container.textContent).toMatch(/synced 2 row/i));
  });

  it("shows setup instructions when sync is not configured", async () => {
    stubFetch({ sync: { synced: false, rows: 0, reason: "not_configured" } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const syncBtn = [...container.querySelectorAll("button")].find((b) => /sync to google/i.test(b.textContent || "")) as HTMLButtonElement;
    fireEvent.click(syncBtn);
    await waitFor(() => expect(container.textContent).toMatch(/not configured/i));
  });
```

Add to `frontend/src/__tests__/client.test.ts`:

```ts
  it("syncSealedLedger POSTs /api/sealed/ledger/sync", async () => {
    const spy = mockFetch(200, { synced: true, rows: 1, reason: null });
    vi.stubGlobal("fetch", spy);
    await syncSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger/sync");
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    vi.unstubAllGlobals();
  });
```

(Add `syncSealedLedger` to the test import.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm --prefix frontend test -- --run SealedLedger`
Expected: FAIL (sync button/cases not yet implemented).

- [ ] **Step 4: Add the sync button + state to SealedLedger.tsx**

Add state near the other state declarations:

```tsx
  const [syncing, setSyncing] = useState(false);
```

Add `syncSealedLedger` to the import from `../api/client`.

Add a handler:

```tsx
  async function sync() {
    setSyncing(true); setError(null); setNotice(null);
    try {
      const res = await syncSealedLedger();
      if (!res.synced && res.reason === "not_configured") {
        setNotice("Google Sheets not configured — place an OAuth client secret at data/credentials.json and set CARDPLATFORM_GOOGLE_SHEET_ID, then sync again.");
      } else if (!res.synced) {
        setNotice(`Sync did not complete: ${res.reason ?? "unknown"}.`);
      } else {
        setNotice(`Synced ${res.rows} row(s) to Google Sheets.`);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Couldn't sync to Google Sheets."); }
    finally { setSyncing(false); }
  }
```

Add the button in the `.deals-toolbar` block (next to Refresh):

```tsx
      <div className="deals-toolbar">
        <button type="button" className="sealed-deals-btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh valuations"}
        </button>
        <button type="button" className="sealed-deals-btn" onClick={sync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync to Google Sheets"}
        </button>
      </div>
```

- [ ] **Step 5: Run the frontend suite + build**

Run: `npm --prefix frontend test -- --run`
Expected: PASS (132 — 128 + 2 component + 1 client + adjust).

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/SealedLedger.tsx frontend/src/__tests__/SealedLedger.test.tsx frontend/src/__tests__/client.test.ts
git commit -m "feat(ledger): Sync to Google Sheets button (Phase 05d T8)"
```

---

## Task 9: Docs + full verify + ship

**Files:**
- Modify: `C:\ClaudeKnowledge\AI_CONTEXT.md` (§2 roadmap row 5 + test-count line + new §16)
- Modify: `C:\ClaudeKnowledge\PROJECT.md` (status + roadmap + next-step)
- Modify: `C:\ClaudeKnowledge\site\app\sections\data.ts` (row 05 subtitle)
- Rebuild: `C:\ClaudeKnowledge\docs\` (site static export — preserve `.nojekyll` + `superpowers/`)
- Ship: commit + push to `origin/main`; confirm GitHub Pages build.

- [ ] **Step 1: Update AI_CONTEXT.md**

- §2 roadmap table, row 5: append to the Status cell —
  `; sealed purchase ledger + profit tracker + Google Sheets sync (OAuth) shipped (§16)`.
- §2 test-count line: update to the actual new counts (run the suites first — backend total
  + frontend total).
- Add a new §16 after §15 (after the §15 block ends). Title:
  `## 16. Phase 05d — Sealed purchase ledger + profit tracker + Google Sheets sync`.
  Content (keep it tight, mirroring §15's shape): one paragraph on the reseller leg (log
  buys, live profit via 05c sold-comps median, append-only valuations, OAuth Sheets sync as
  a mirror), the two new tables (`sealed_purchases` user-editable + `sealed_valuations`
  append-only, auto-provisioned by `create_all()`), the routes
  (`GET/POST/DELETE /sealed/ledger`, `POST /sealed/ledger/valuate[/{id}]`,
  `POST /sealed/ledger/sync`), the CLI (`log/list/valuate/sync-sealed-ledger`), the 8th
  "Ledger" tab, the Google setup story (OAuth Desktop client secret at
  `data/credentials.json`, `CARDPLATFORM_GOOGLE_SHEET_ID`, browser sign-in, token at
  `data/google_token.json` — both gitignored), and the sacred-constraints note (profit reads
  latest persisted valuation — never ad hoc; valuations append-only; honest empties —
  `—`/not-configured, never `$0`; Sheets is a mirror that degrades to not-configured).

- [ ] **Step 2: Update PROJECT.md**

Update the status header, the roadmap row 5 (append ledger shipped), and the Next-step
section (next = rip EV still data-blocked / sealed-product master, OR set-completion
optimizer Phase 06).

- [ ] **Step 3: Update the site roadmap row**

`site/app/sections/data.ts`, row `n: "05"` — append to the subtitle:
`; sealed purchase ledger + profit tracker + Google Sheets sync shipped`.

- [ ] **Step 4: Run the full verification matrix**

```bash
cd C:\ClaudeKnowledge
backend\.venv\Scripts\python.exe -m pytest -q                       # backend total, all green
npm --prefix frontend test -- --run                                  # frontend total, all green
npm --prefix frontend run build                                      # clean
npm --prefix site run build                                          # clean
backend\.venv\Scripts\python.exe backend\scripts\evaluate_detection.py  # 105-scan baseline, 0 regressions
```

Record the actual backend + frontend test counts for the AI_CONTEXT test-count line + this
plan's summary. All must be green; the 105-scan baseline must show 0 regressions (no
recognition code changed this phase).

- [ ] **Step 5: Rebuild docs/ safely (do NOT rm -rf docs)**

```bash
cd C:\ClaudeKnowledge
# Remove only the generated site files, preserving docs/.nojekyll + docs/superpowers/.
Remove-Item docs\404, docs\404.html, docs\_next, docs\index.html, docs\index.txt -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item site\out\* docs\ -Recurse -Force
# Confirm the preserved dirs are intact:
Test-Path docs\.nojekyll
Test-Path docs\superpowers\plans
Test-Path docs\superpowers\specs
```

(On PowerShell, `Remove-Item ... -ErrorAction SilentlyContinue` skips files that don't exist.
If the shell is bash, use `rm -rf` only on the specific generated paths, never `docs/`
itself, and never `docs/.nojekyll` or `docs/superpowers/`.)

- [ ] **Step 6: Commit + push**

```bash
cd C:\ClaudeKnowledge
git add AI_CONTEXT.md PROJECT.md site/app/sections/data.ts docs/
git commit -m "docs(ledger): Phase 05d shipped — ledger + profit + Google Sheets sync (T9)"
git push origin main
```

- [ ] **Step 7: Confirm GitHub Pages build**

```bash
gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds --jq '.[0].status'
```

Expected: `built` (not `errored`). If `errored`, inspect the build log; the most common
cause is a missing `docs/.nojekyll` (verify Step 5 preserved it).

- [ ] **Step 8: Final summary**

Report: backend test count, frontend test count, 105-scan baseline result, the new routes +
CLI + tab, the Google setup story, and the commit SHA + Pages build status. Note any minor
follow-ups (8-tab mobile crowding; rip EV still data-blocked).

---

## Self-review checklist (run before dispatching subagents)

- **Spec coverage:** Every spec § (1 goal, 2 scope, 4 architecture, 5 file structure, 6
  constraints, 7 math, 8 OAuth/sync, 9 open questions) maps to a task. Spec §7 profit math
  → T2 `LedgerService.list_ledger`. Spec §8 OAuth → T6; sync → T7. §5 file structure → all
  tasks. No spec requirement lacks a task.
- **Placeholder scan:** No "TBD"/"implement later" — every code step has real code. The two
  "read the existing test file for the idiom" instructions (T3 session override, T1 mirrors)
  are deliberate, not placeholders — they avoid hardcoding an unverified pattern.
- **Type consistency:** `LedgerEntry` fields (T2) → `SealedLedgerEntryOut` (T3) → TS
  `SealedLedgerEntry` (T5) → render — names + nullability line up. `SheetsSyncResult` (T7)
  → `SheetsSyncResultOut` (T3, defined early) → TS `SheetsSyncResult` (T8) → render.
  `ValuationRefreshResult` (T2) → `ValuationRefreshResultOut` (T3) → TS (T5). `build_sheet_rows`
  defined T7, used by API (T7) + CLI (T7) — same signature.
- **Dependency ordering:** T1 models → T2 service (needs models) → T3 API (needs service) →
  T4 CLI (needs service) → T5 frontend (needs API) → T6 OAuth → T7 sync (needs T6 client +
  T2 service) → T8 frontend sync (needs T7 API) → T9 docs (needs all). No forward refs.
- **Shippable checkpoint:** After T5 the local ledger is complete + green + committed (the
  Google sync is purely additive on top). After T8 the full feature is green. T9 ships.