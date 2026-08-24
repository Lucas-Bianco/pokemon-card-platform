# Insurance value + price provenance + trend honesty — Implementation Plan

**Goal:** Ship roadmap row 18 (collection insurance value), row 22 (market trend charts, honest), and the Phase H "TCGplayer market reference vs eBay proven" enhancement the user chose.

**Architecture:** Backend for insurance only — `CollectionStore.insurance_value()` computes conservative/median/aggressive bands from each holding's `latest_price` snapshot (`low`/`market`/`high`), unpriced cards excluded never $0, plus a printable per-card schedule. New `GET /collection/insurance`. Phase H and Phase 22 are frontend-only: `PriceLine` gains a `showBand` prop (low/mid/high + clear source label) used in `CardDetail`; `CardDetail` adds a one-line "market reference (ask) vs proven eBay sales (transactions)" provenance caveat; `PriceChart` adds an honest "depth depends on refresh cadence; snapshots are append-only, never trimmed" caption. No new price provider, no schema change, no migration. Honest empty states throughout; source + staleness on every figure.

**Tech stack:** FastAPI + SQLAlchemy 2.0 + Pydantic v2 (backend); React 19 + vitest (frontend).

**Sacred constraints (must hold):** never $0 (em dash / "no market price"); never fabricate; surface `source` + `source_updated_at`; `""` sentinel → None on the wire; unpriced excluded from totals, counted not guessed; `func.lower(col).like` not ilike; `getByRole("button",{name:"Scan"})` resolves to exactly one element; new tab labels ≠ "Scan"; Dashboard CTAs are distinct verb-phrases.

---

## Task 1 — Phase 18 backend: `CollectionStore.insurance_value()`

**Files:** Modify `backend/src/cardplatform/collection/store.py`; Test `backend/tests/test_collection_insurance.py`.

- [ ] Write failing tests: 3-band sums (low/market/high × qty), unpriced excluded + counted, mixed priced/unpriced, low/high fallback to market when None, schedule completeness (every holding listed with priced flag), source + staleness carry (`""` → None), empty collection → all-zero bands + 0 items, never-$0.
- [ ] Implement `InsuranceValue` + `InsuranceLine` frozen dataclasses + `insurance_value()` method reusing `self.prices.latest_price`. conservative = `low ?? market`; median = `market`; aggressive = `high ?? market`; priced iff `market is not None`.
- [ ] Run `pytest backend/tests/test_collection_insurance.py -v` → PASS.

## Task 2 — Phase 18 backend: route + wire models

**Files:** Modify `backend/src/cardplatform/api.py` (models near line 524, route near line 1071, `_insurance_*_out` helper).

- [ ] Add `InsuranceLineOut` + `InsuranceValueOut` (Pydantic v2, `ConfigDict(from_attributes=True)`), `InsuranceValueOut` with `conservative/median/aggressive/priced_items/unpriced_items/schedule/caveat`.
- [ ] Add `GET /collection/insurance` route registered BEFORE `PATCH /collection/{item_id}` (literal path before parameterised — mirrors the portfolio route comment at line 1069).
- [ ] Test via `test_collection_insurance_api.py`: round-trip, empty collection, mixed bands, `""` source_updated_at → None.
- [ ] Run `pytest` → all backend green.

## Task 3 — Phase 18 frontend: types + client + Vault panel + schedule

**Files:** Modify `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/components/PortfolioView.tsx`, `frontend/src/styles.css`; Test `frontend/src/__tests__/InsuranceValue.test.tsx`.

- [ ] `InsuranceLine` + `InsuranceValue` types; `getInsuranceValue()` client (`GET /collection/insurance`, `expectJsonOrDetail`).
- [ ] `PortfolioView`: insurance panel in the valuation block (3 band tiles + priced/unpriced + caveat), gated by `hasHoldings`; "View schedule" toggle → table (card/variant/qty/low/market/high/source/staleness) + "Print" button (`window.print()`). Em dash for null; `@media print` hides everything but the schedule.
- [ ] Tests: renders 3 bands, unpriced-excluded note, schedule toggle open/close, print button present, never `$0.00` for unpriced.
- [ ] Run `vitest` → green.

## Task 4 — Phase H: price provenance in CardDetail

**Files:** Modify `frontend/src/components/PriceLine.tsx`, `frontend/src/components/CardDetail.tsx`; tests.

- [ ] `PriceLine`: add `showBand?: boolean`. When true, render market (strong) + `low · mid · high` band + label ("TCGplayer market reference" / "Cardmarket aggregate" / raw source) + staleness. Default compact for `ScanResult`.
- [ ] `CardDetail`: `<PriceLine ... showBand />` + provenance caveat between PriceLine and SoldComps: market reference is an ask; eBay sales below are proven transactions; two honest figures that can differ; if reference unavailable, sales may still have evidence.
- [ ] Tests: PriceLine showBand renders band + label; compact mode unchanged; CardDetail renders caveat; scan test still passes.
- [ ] Run `vitest` → green.

## Task 5 — Phase 22: PriceChart honesty caption

**Files:** Modify `frontend/src/components/PriceChart.tsx`; test.

- [ ] Multi-point view: add caption "N points · depth depends on price-refresh cadence (snapshots are append-only, never trimmed)". Keep empty/1-point honesty.
- [ ] Test: multi-point renders caption with point count.
- [ ] Run `vitest` → green.

## Task 6 — Docs + verify + ship

- [ ] `site/app/sections/data.ts`: row 18 → "done"; row 22 → "done" with honest subtitle correcting the "trimmed" false premise.
- [ ] `pytest` (backend, all green) + `vitest` (frontend, all green) + `tsc` + `vite build` clean. Confirm 105-scan baseline untouched.
- [ ] Commit + push to origin/main.
- [ ] Run dev servers (backend :8000 + frontend :5173 --host); stop per run-loop.