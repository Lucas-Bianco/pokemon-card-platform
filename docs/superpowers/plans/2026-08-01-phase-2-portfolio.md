# Phase 2 — Portfolio Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the collection from a flat holdings list into a portfolio: per-item market value and unrealized P/L, an allocation/top-movers summary, cost-basis editing and removal, and an honest price-history chart that renders a single dot as "need more history" rather than faking a trend.

**Architecture:** All valuation stays server-side — the frontend never resolves "the latest price" itself (project rule). Three net-new backend surfaces: `PriceService.price_history`, `CollectionStore.portfolio/summary/set_cost_basis`, and four endpoints layered on them. The frontend grows a hand-rolled SVG chart (zero new deps) and a `PortfolioView` that supersedes `CollectionView` while preserving its em-dash-for-missing-data conventions. Existing `GET /collection` and `GET /collection/valuation` are left untouched so the scan add-to-collection flow and its tests stay stable.

**Tech Stack:** SQLAlchemy ORM queries over the existing immutable `PriceSnapshot` table; FastAPI pydantic models; React 19 + inline SVG; vitest/jsdom. No new libraries.

---

## Context

The public roadmap (`docs/index.html`) lists Phase 2 Portfolio tracker as the next Planned phase after 01c (done) and 03a centering (done but not yet shown on the public site). `AI_CONTEXT.md` §6 blocked Phase 2 on DATA: 0 of 37 collection items had a cost basis, and 0 price series had more than one `source_updated_at`. Both causes are now unblocked but need time to accrue (scan flow asks "what you paid"; `refresh-collection-prices` accrues history).

**The decisive constraint:** Phase 2 ships code that is correct now and becomes useful as data accrues. A chart with one snapshot renders a single dot and says "need more history"; P/L with no cost basis renders an em-dash, never `+$0.00` and never market value as profit. This is the same "never fake missing data" value the existing `CollectionView` em-dash already encodes.

### Measured findings this plan is built on (verified 2026-08-01)

- `CollectionItem` (`backend/src/cardplatform/db/models.py:113-126`) **already** has `acquired_price`, `acquired_at`, `notes`, `condition`, `variant`, `quantity`, `created_at`. No migration needed — the columns exist but are unused by the current store/API.
- `CollectionStore.add` (`collection/store.py:27-55`) merges rows on `(card_id, variant)`, **ignores** the new `acquired_price` on re-add, and **never sets `acquired_at`**. The 37 existing rows have `acquired_at IS NULL` and can't be backfilled through `add`.
- `PriceService` (`prices/service.py:50-73`) has no history method — only `_newest`/`latest_price`. The append-only `PriceSnapshot` table with `ix_snapshot_lookup(card_id, variant, source, fetched_at)` and `uq_snapshot(card_id, source, variant, source_updated_at)` is already shaped for history; the query just doesn't exist.
- `GET /cards/{id}/prices` (`api.py:272-288`) collapses history to newest-per-`(source, variant)`. No series endpoint.
- `CollectionItemOut` omits `acquired_at`, `notes`, and any market value; `CollectionItemIn` omits `acquired_at`/`notes`; no PATCH/DELETE endpoint (`store.remove` exists but isn't wired to HTTP).
- Frontend `client.ts` has `getCollection`, `getValuation`, `addToCollection` — no remove, no update, no history. `CollectionView.tsx` renders the em-dash when `cost_basis === 0`; this convention carries forward.
- No chart library installed (`package.json` only react/react-dom). Minimal-deps ethos favours hand-rolled SVG.

---

## Scope

### Decisions (trade-offs weighed, then committed)

1. **New `GET /collection/portfolio` endpoint, not extending `CollectionItemOut`.** Extending `CollectionItemOut` would change `GET /collection`'s shape, whose tests assert exact dicts and whose consumer (scan add-to-collection) needs no market value. A new endpoint with new output models keeps the existing surface + tests stable and gives the portfolio a purpose-built shape: enriched items + summary in one round trip. **Leave `GET /collection` and `GET /collection/valuation` untouched.**
2. **Summary rides in the portfolio response.** `CollectionStore.portfolio() -> Portfolio` returns items + summary together (one fetch, not two). Summary = existing `Valuation` fields plus `priced_items`, `allocation` (by set), and `top_gainers`/`top_losers` (top 3 each, only items with both a price and a cost basis).
3. **Price history: one point per `source_updated_at`, tcgplayer-preferred, each point carrying `source` + `source_updated_at`.** Mirrors `latest_price`'s tcgplayer-then-cardmarket/aggregate resolution per date, so the chart shows the same notion of "the price" the rest of the app uses, and staleness stays surfaced. When both sources share a date, tcgplayer wins; cardmarket-only dates still appear as their own points. `PriceService.price_history(card_id, variant, since=None, days=None) -> list[PriceSnapshot]`; `GET /cards/{card_id}/prices/history?variant=&days=`.
4. **Cost-basis editing via `CollectionStore.set_cost_basis(item_id, ...)` + `PATCH /collection/{item_id}`.** Editing by row id is unambiguous. `add` also starts stamping `acquired_at = now(utc)` on **new** rows only (merged rows keep their existing `acquired_at` — a top-up is not a new purchase). The per-`(card, variant)` one-row model stays; lot-level refactor is out of scope.
5. **Remove via `DELETE /collection?card_id=&variant=&quantity=`** (query params match existing `refresh_price` style; `store.remove` already a no-op for unknown cards).
6. **Hand-rolled SVG `PriceChart.tsx`, no new dependency.** Empty state "No price history yet"; single-point state one dot + "Need more history to draw a trend"; multi-point a polyline with min/max/current labels + a caption naming the latest `source`/`source_updated_at`. Market-null points are skipped with a note, never drawn as a flat zero line.
7. **Evolve `CollectionView` into `PortfolioView`.** Sections: summary grid (carried over), allocation-by-set, top movers, holdings table with per-row market price + unrealized P/L + History/Edit/Remove actions. App switches `showCollection: boolean` → `view: "scan"|"portfolio"` enum. Delete `CollectionView.tsx`.
8. **Docs:** `AI_CONTEXT.md`, `PROJECT.md`, `docs/index.html`, and this plan file. Listed precisely in Task 7.
9. **Git:** branch `phase-2-portfolio`, TDD per task, commit per task, merge to `main`, push (so GitHub Pages deploys the updated `docs/index.html`).
10. **Verification:** pytest, `npm test`, `npm run build`, + manual smoke seeding a cost-basis item with two snapshots on different dates, hitting the new endpoints, and rendering the chart with both a multi-point and a single-point series.

### Out of scope

- Lot-level collection model (one row per purchase). Re-add still tops up quantity and ignores new `acquired_price`.
- Blending sources into one "market price" number. Each history point carries its `source`.
- Predictive trends / projections. Chart plots observed points only.
- Bulk backfill of cost basis for the 37 existing items (PATCH enables per-item backfill; doing it is a data task).

---

## File structure

```
backend/src/cardplatform/
  prices/service.py         # + price_history()
  collection/store.py       # + Portfolio, PortfolioItem, PortfolioSummary, Allocation dataclasses
                            # + portfolio(), summary(), set_cost_basis(); add() sets acquired_at on new rows
  api.py                    # + PortfolioItemOut, PortfolioSummaryOut, AllocationOut, PortfolioOut,
                            #   PricePointOut, PriceHistoryOut, CollectionItemUpdate (+ notes on CollectionItemIn)
                            # + GET /collection/portfolio, PATCH /collection/{id}, DELETE /collection,
                            #   GET /cards/{id}/prices/history
backend/tests/
  test_price_service.py     # + price_history tests
  test_collection.py        # + portfolio/summary/set_cost_basis/acquired_at tests
  test_api.py               # + new endpoint tests
frontend/src/
  api/types.ts              # + PricePoint, PriceHistory, PortfolioItem, Allocation, PortfolioSummary, Portfolio
  api/client.ts             # + getPortfolio, patchCollectionItem, removeFromCollection, getPriceHistory
  components/PriceChart.tsx     # new — hand-rolled SVG
  components/PortfolioView.tsx  # new — supersedes CollectionView
  components/CollectionView.tsx # delete after App switches
  App.tsx                   # view enum "scan"|"portfolio"; header button
  styles.css                # + portfolio/chart styles
frontend/src/__tests__/
  client.test.ts            # + new fetch functions
  PriceChart.test.tsx       # new
  PortfolioView.test.tsx    # new
docs/superpowers/plans/2026-08-01-phase-2-portfolio.md  # this plan, saved into the repo
AI_CONTEXT.md, PROJECT.md, docs/index.html   # updated in Task 7
```

---

## Task 1: Price history on PriceService

**Files:** `backend/src/cardplatform/prices/service.py`, `backend/tests/test_price_service.py`

- [ ] **Step 1: Write failing tests** reusing the `snapshot(session, card_id, source, variant, market, source_updated_at=...)` helper pattern. Cover: ordered oldest-first; dedupes repeated fetches for same source date (newest `fetched_at` wins); tcgplayer-preferred over cardmarket on same date but cardmarket-only dates still appear; cardmarket aggregate prices `normal` variant (mirrors `latest_price` fallback); `since`/`days` filter excludes older; empty when no snapshots.
- [ ] **Step 2: Implement `price_history(self, card_id, variant, since=None, days=None) -> list[PriceSnapshot]`.** Query tcgplayer rows for `variant` plus cardmarket rows for `"aggregate"` (same pair `latest_price` uses), optionally filtered by `since` (derived from `days`), dedupe per `(source, source_updated_at)` keeping newest `fetched_at`/`id`, collapse per `source_updated_at` preferring tcgplayer, sort ascending by `fetched_at` (the indexed datetime — `source_updated_at` is free-text whose format differs between sources and sorts only within one source). Each returned point carries its own `source` + `source_updated_at`.
- [ ] **Step 3:** `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_service.py` → green.
- [ ] **Step 4: Commit** `phase-2: PriceService.price_history`.

## Task 2: Portfolio, summary, cost-basis editing on CollectionStore

**Files:** `backend/src/cardplatform/collection/store.py`, `backend/tests/test_collection.py`

- [ ] **Step 1: Write failing tests.** `portfolio()` item carries `market_price`/`unrealized`/`priced`; unpriced item has `market_price=None`/`unrealized=None`/`priced=False`; item without cost basis has `market_price` set but `unrealized=None`; `summary` allocation groups by set (sorted by market_value desc); top gainers/losers only include items with both price and cost basis; summary counts priced vs unpriced; `set_cost_basis` updates `acquired_price`/`acquired_at`/`condition`/`notes` and raises `ValueError` for unknown id; `add` now stamps `acquired_at` on new rows; `add` merge does not overwrite existing `acquired_at`.
- [ ] **Step 2: Add dataclasses** `PortfolioItem`, `Allocation`, `PortfolioSummary`, `Portfolio` (frozen dataclasses). `PortfolioItem` fields: id, card_id, card_name, set_id, set_name, variant, quantity, acquired_price, acquired_at, condition, notes, market_price, market_source, market_source_updated_at, unrealized (None when price or cost basis missing), priced. `PortfolioSummary`: the `Valuation` fields + `priced_items` + `allocation: list[Allocation]` + `top_gainers`/`top_losers: list[PortfolioItem]` (top 3 each). `Portfolio`: {summary, items}.
- [ ] **Step 3: Implement `portfolio()` and `summary()`.** Per item call `self.prices.latest_price(card_id, variant)` (the project rule — never ad hoc). `unrealized = (market - acquired_price) * quantity` only when both `market is not None` and `acquired_price is not None`; else `None`. `priced = snapshot is not None and snapshot.market is not None`. Allocation groups by `card.card_set`, sums market_value + cost_basis, counts items, sorts by market_value desc. Top movers filter to `unrealized is not None`, sort desc/asc, take 3.
- [ ] **Step 4: Implement `set_cost_basis(item_id, acquired_price, acquired_at=None, condition=None, notes=None) -> CollectionItem`** — `session.get`, raise `ValueError(f"unknown item: {item_id!r}")` if None, set fields, commit, return item.
- [ ] **Step 5: Update `add`** to set `acquired_at=datetime.now(timezone.utc)` on **new** rows only (not the merge branch). Add `from datetime import datetime, timezone`.
- [ ] **Step 6:** `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_collection.py` → green.
- [ ] **Step 7: Commit** `phase-2: CollectionStore portfolio, summary, set_cost_basis, acquired_at`.

## Task 3: API endpoints

**Files:** `backend/src/cardplatform/api.py`, `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests** (reuse `client`/`seeded`/`snapshot` fixtures, assert exact shapes): `GET /collection/portfolio` returns items with `market_price`/`unrealized`/`priced` and summary (`market_value`/`cost_basis`/`unrealized`/`priced_items`); item with no cost basis has `unrealized: null`; `GET /cards/{id}/prices/history?variant=` returns `points` oldest-first with `source`; `days` filter; empty → `points: []`; `PATCH /collection/{id}` updates `acquired_price` (200) and 404 for unknown; `DELETE /collection?card_id=&variant=&quantity=` decrements (204) and deletes the row at zero.
- [ ] **Step 2: Add pydantic models** `PortfolioItemOut`, `AllocationOut`, `PortfolioSummaryOut`, `PortfolioOut`, `PricePointOut`, `PriceHistoryOut`, `CollectionItemUpdate`. Extend `CollectionItemIn` with `notes: str | None = None` (additive; leave `CollectionItemOut` as-is so `GET /collection` test shapes stay stable).
- [ ] **Step 3: Add endpoints** inside `create_app()`: `GET /collection/portfolio` (response_model=PortfolioOut), `PATCH /collection/{item_id}` (response_model=CollectionItemOut; `ValueError`→404), `DELETE /collection` (query params `card_id`/`variant`/`quantity`; returns 204), `GET /cards/{card_id}/prices/history` (query `variant`/`days`; response_model=PriceHistoryOut; 404 for unknown card — reuse existing 404 helper if present, else add `_require_card`). Register `/cards/{card_id}/prices/history` right after `get_card_prices` so the deeper literal isn't shadowed.
- [ ] **Step 4: Add helpers** `_portfolio_item_out`, `_allocation_out`, `_summary_out`. Each point's `source`/`source_updated_at` flow through from the snapshot (the `_price_out` "never drop staleness" rule generalised).
- [ ] **Step 5:** `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest` → green (full suite).
- [ ] **Step 6: Commit** `phase-2: portfolio, history, PATCH, DELETE endpoints`.

## Task 4: Frontend types and API client

**Files:** `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/__tests__/client.test.ts`

- [ ] **Step 1: Write failing tests** mirroring the existing `mockFetch` + URL-substring/body-shape pattern: `getPortfolio` → `/api/collection/portfolio`; `patchCollectionItem` PATCHes `/api/collection/{id}` with JSON body; `removeFromCollection` DELETEs `/api/collection?card_id=&variant=&quantity=`; `getPriceHistory` → `/api/cards/{id}/prices/history?variant=&days=`; returns `{points:[]}` on 200.
- [ ] **Step 2: Add types** `PricePoint`, `PriceHistory`, `PortfolioItem`, `Allocation`, `PortfolioSummary`, `Portfolio` to `types.ts`.
- [ ] **Step 3: Add client functions** `getPortfolio()`, `patchCollectionItem(id, update)`, `removeFromCollection(cardId, variant, quantity=1)`, `getPriceHistory(cardId, variant, days?)`. Use `expectJson` where a body is expected; for PATCH/DELETE check `res.ok` (DELETE treats 204 as success).
- [ ] **Step 4:** `npm --prefix C:\ClaudeKnowledge\frontend test` and `npm run build` → green.
- [ ] **Step 5: Commit** `phase-2: frontend types + api client for portfolio/history`.

## Task 5: PriceChart component (hand-rolled SVG)

**Files:** `frontend/src/components/PriceChart.tsx`, `frontend/src/__tests__/PriceChart.test.tsx`, `frontend/src/styles.css`

- [ ] **Step 1: Write failing tests** (`render` + `container.textContent`, jsdom — no layout): empty → "No price history yet"; one point → a dot + "need more history" note; multiple points → polyline + current/min/max labels; latest point's `source`/`source_updated_at` surfaced in a caption; all-null market → "unpriced" note rather than a flat zero line.
- [ ] **Step 2: Implement `PriceChart.tsx`** (props `{ points: PricePoint[]; variant: string; onClose?: () => void }`). Filter to non-null `market`; if <2 non-null, render the single-dot state. Inline `<svg viewBox>` with `<polyline>` through market values, min/max/current labels, and a caption with the latest point's `source` + `source_updated_at` (staleness convention — never present a price without its source). No external library.
- [ ] **Step 3: Add styles** to `styles.css` (`.price-chart`, match existing CSS custom properties / dark scheme).
- [ ] **Step 4:** `npm test` and `npm run build` → green.
- [ ] **Step 5: Commit** `phase-2: PriceChart hand-rolled SVG with honest empty/single states`.

## Task 6: PortfolioView and App wiring

**Files:** `frontend/src/components/PortfolioView.tsx`, `frontend/src/App.tsx`, `frontend/src/components/CollectionView.tsx`, `frontend/src/styles.css`, `frontend/src/__tests__/PortfolioView.test.tsx`

- [ ] **Step 1: Write failing component test.** Stub `fetch` to return a `Portfolio` with one priced item (cost basis + market) and one unpriced item. Assert: summary grid shows market value / cost basis / unrealised with `+`/`−` colouring; em-dash when `cost_basis === 0`; "no purchase prices recorded" note; holdings table shows per-item market price and unrealised P/L; unpriced item shows `—` and "no market price" (not `$0.00`); a "History" button per row; stub a second fetch for history and assert the chart renders.
- [ ] **Step 2: Implement `PortfolioView.tsx`** (props `{ onBack }`), carrying `CollectionView`'s conventions verbatim: header + back; summary grid (reuse exact em-dash logic + the "no purchase prices recorded" and "unpriced items" notes); allocation-by-set list (hide when ≤1 set); top movers (hide when empty — cost basis not yet recorded); holdings table — quantity, name, variant, set, paid (em-dash if null), market (`—` + "no market price" tag if unpriced), unrealised (em-dash if null), a "History" button fetching `getPriceHistory` and rendering `<PriceChart>` inline, an "Edit" control posting `patchCollectionItem` then reload, a "Remove" button calling `removeFromCollection` then reload. Loading/error states matching the existing pattern.
- [ ] **Step 3: Wire into `App.tsx`** — replace `useState<boolean>` with `const [view, setView] = useState<"scan"|"portfolio">("scan")`; header button → `"portfolio"`; `onBack` → `"scan"`. Remove the `CollectionView` import.
- [ ] **Step 4: Delete `CollectionView.tsx`** (subsumed by `PortfolioView`; a dead file misleads future readers).
- [ ] **Step 5: Add portfolio/table styles** to `styles.css` (`.portfolio`, `.portfolio-table`, `.allocation`, `.movers`; reuse `.valuation`, `.muted`, `.up`, `.down`, `.unknown`).
- [ ] **Step 6:** `npm test` and `npm run build` → green.
- [ ] **Step 7: Commit** `phase-2: PortfolioView replaces CollectionView; App view toggle`.

## Task 7: Docs updates, merge, and push

**Files:** `AI_CONTEXT.md`, `PROJECT.md`, `docs/index.html`, `docs/superpowers/plans/2026-08-01-phase-2-portfolio.md`

- [ ] **Step 1: Save this plan** into the repo at `docs/superpowers/plans/2026-08-01-phase-2-portfolio.md`.
- [ ] **Step 2: Update `AI_CONTEXT.md`:** §2 table Phase 2 → ✅ Complete; "Last updated" → 2026-08-01; test-count line → new totals. §6 rewrite: Phase 2 shipped, becomes useful as cost basis + price history accrue; code correct now (single-dot chart, em-dash P/L); re-measure price-history series count (>1 distinct source date) on 2026-08-01. §3 Layout: add `collection/store.py — portfolio/summary/set_cost_basis`, `prices/service.py — price_history`, `components/PortfolioView.tsx, PriceChart.tsx`. Add a note on the four new endpoints + "never blend sources; each history point carries source + source_updated_at". §7: drop Phase 2 as a lever; next levers are Phase 3a centering coverage + Phase 3 full grading (blocked on data).
- [ ] **Step 3: Update `PROJECT.md`:** roadmap table Phase 2 → Complete; add a "## Phase 2 — shipped" section with measured findings, endpoints shipped, and the honest-empty-states decision; note lot-level + source-blending stay out of scope.
- [ ] **Step 4: Update `docs/index.html`** (the roadmap `<section>` lines 153-172): **verify** the `01c` row is present and `st done` (the local file already has it; the *deployed* site is stale — only add if missing, to avoid a duplicate). Add an `03a` row after `02`: "Card centering · Geometric PSA cap from border measurement · correct, coverage blocked on real photos" / `st done`. Mark `02` → `st done` Complete with subtitle "Cost basis, P/L, price history charts · honest empty states". Footer "Last updated" → 2026-08-01.
- [ ] **Step 5: Final verification** — `python -m pytest`; `npm test`; `npm run build` all green.
- [ ] **Step 6: Manual smoke.** Backend running; seed one collection item with a cost basis + two snapshots on different `source_updated_at` dates. `GET /collection/portfolio` → item has `market_price`/`unrealized`/`priced=true`; summary allocation lists the set; top_gainers contains the item. `PATCH /collection/{id}` → reflected on next GET. `DELETE /collection?...&quantity=1` → decrements. `GET /cards/{id}/prices/history?variant=holofoil` → two points oldest-first, each carrying `source`/`source_updated_at`. In the browser: Portfolio summary + allocation + holdings table render; click "History" → multi-point chart; point at a single-snapshot card → single-dot + "need more history"; unpriced card → em-dash + "no market price".
- [ ] **Step 7: Commit** `phase-2: update AI_CONTEXT, PROJECT, index.html, plan`.
- [ ] **Step 8: Merge to `main` and push** so GitHub Pages deploys the updated `docs/index.html`:
  `git checkout main && git merge --no-ff phase-2-portfolio && git push origin main`

---

## Definition of done

- [ ] `python -m pytest` passes (existing + new backend tests).
- [ ] `npm test` passes (existing + new frontend tests).
- [ ] `npm run build` passes.
- [ ] `GET /collection/portfolio` returns per-item `market_price`/`unrealized`/`priced` + summary with allocation and top movers, all computed server-side via `PriceService.latest_price`.
- [ ] `PriceService.price_history` returns one point per `source_updated_at`, tcgplayer-preferred, each point carrying `source` + `source_updated_at`; endpoint returns points oldest-first and empty `points` when none.
- [ ] `PATCH /collection/{id}` updates cost basis / `acquired_at` / `condition` / `notes`; `DELETE /collection` decrements and deletes at zero; both exercised by tests.
- [ ] `add` stamps `acquired_at` on new rows and doesn't overwrite it on merge.
- [ ] `PriceChart` renders "No price history yet" / single dot + "need more history" / polyline + current-min-max + source caption; never a flat zero line for unpriced points.
- [ ] `PortfolioView` preserves em-dash-for-missing-cost-basis + "never guessed" conventions; unpriced items show `—` + "no market price", not `$0.00`.
- [ ] Manual smoke passes with a multi-point and a single-point series.
- [ ] `AI_CONTEXT.md` (incl. "Last updated" + §6 rewrite), `PROJECT.md`, `docs/index.html` (03a row added, 02 Complete, footer date), and the plan file updated.
- [ ] Branch `phase-2-portfolio` merged to `main` and pushed.

## What stays blocked after this

- **Useful charts and meaningful P/L still depend on accrued data.** The code is correct now; it becomes useful as the owner records cost basis on scans and `refresh-collection-prices` accrues multi-date history. The honest empty/single states are the feature, not a workaround.
- **Lot-level cost basis.** Re-adding the same `(card, variant)` still tops up one row and ignores the new `acquired_price`; a per-purchase lot model is deferred.
- **Source blending / a single canonical "market price" series.** Each history point carries its own `source`; the chart plots the tcgplayer-preferred resolved point per date but never invents a blended number.
- **Phase 3 full grading** (corners, edges, surface, grading EV) remains blocked on labelled graded-card data (`AI_CONTEXT.md` §6/§9).