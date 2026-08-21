# Phase 06 — Set-Completion Optimizer Design

> **Status:** design, 2026-08-21. Auto-mode spec (no per-step check-ins): design decisions
> are made here with defaults rather than asked one-at-a-time, per the standing directive.
> The next unblocked roadmap item — rip EV and the full learned Grade predictor are both
> still data-blocked (no pull rates; 0 labelled scans). This is the honest feature that
> *can* ship on the data the project already has: the catalog (174 sets / 20,444 cards) +
> the user's collection (39 items) + `PriceService.latest_price`.

## 1. Goal

Show a collector, per Pokémon TCG set, **what they still need to complete it** and the
**honest estimated cost to get there**: the full checklist (every card in the set, ordered
by collector number), each marked owned / missing, with the current market price for the
missing ones. A completion summary gives owned / total / % complete / estimated cost to
complete (sum of missing-card market prices) with the count of unpriced missing cards
shown separately — never `$0`, never fabricated.

## 2. Scope — what ships, what's deferred

**Ships (read-only, no new tables, no migrations):**
- A `CompletionService` (`catalog/completion.py`) that joins the catalog (cards + sets) to
  the collection and resolves missing-card prices through `PriceService.latest_price` —
  the sacred price path, never ad-hoc.
- `GET /sets` (searchable list of all sets with per-set owned/total progress) and
  `GET /sets/{set_id}` (the full checklist + completion summary).
- A 10th **Sets** frontend tab (`Sets.tsx` — searchable set list with progress bars) and a
  `SetDetail.tsx` overlay (AppShell `selectedSet` state, mirroring the `selectedCard` /
  CardDetail overlay) showing the checklist grid + summary KPIs. Clicking a checklist card
  opens the existing `CardDetail` overlay.
- Additive CSS (`.sets-*`, `.set-detail-*`, `.checklist-*`); the mobile bottom-nav becomes
  horizontally scrollable (`overflow-x: auto`) so 10 tabs fit without crowding — a
  visual-only change that does not touch any test-queried name/class.

**Deferred (documented follow-ups, NOT this phase):**
- **Per-variant completion** — completion is by card (collector number): owning *any* variant
  counts as owned. Per-variant tracking (normal vs holofoil vs reverse holo, and which
  variant you own) is a follow-up. YAGNI for the first cut.
- **Cheapest-listing acquisition path** — "buy this missing card for $X on eBay" needs the
  listings provider wired per checklist card; deferred (the listings API is card-keyed and
  already exists, but fan-out over 100+ cards per set is a separate, rate-limit-aware
  design). The summary uses market price, the same notion of "the price" the rest of the
  app uses.
- **Set wishlist / trade binder** — "cards I have to trade away" / duplicates. Not now.
- **Keyboard shortcut for the 10th tab** — AppShell maps `1`–`9` to tabs; a 10th tab is
  reachable by click and via the command palette, not by a `1`-`9` shortcut. Mapping `0`
  is a minor follow-up; not blocking.

## 3. Architecture

### 3.1 Backend — `catalog/completion.py`

`CompletionService(session, price_service: PriceService)` (price_service constructed without a
provider, read-only — same pattern as collection valuation):

- `list_sets(query: str | None = None) -> list[SetProgress]`
  - All `CardSet` rows, optionally filtered by `func.lower(CardSet.name).like(...)` (NOT
    `ilike` — accents; the sacred constraint). Ordered by `release_date DESC` then `name`
    (newest sets first, the collector-relevant order).
  - Owned per set = distinct `CollectionItem.card_id` joined to `Card.set_id`. Computed in
    one grouped query (LEFT JOIN cards → collection, `count(distinct collection_items.card_id)`
    grouped by set), not N queries.
  - Checklist size per set = `count(Card)` grouped by `set_id` (the real set of cards in the
    DB — for me5 this is 120, matching `total`; for sets where the catalog has secret rares
    beyond `printed_total`, the DB count is the honest checklist).
  - Returns `SetProgress(id, name, series, release_date, total, printed_total, owned,
    checklist_size, pct_complete)`. `pct_complete = owned / checklist_size` (0 when
    checklist_size 0 — never a divide-by-zero, never fabricated). `total` is the official
    declared total carried for reference; completion is measured against `checklist_size`.

- `set_detail(set_id: str) -> SetCompletion`
  - The set row (404 if missing — `_require_set` helper mirroring `_require_card`).
  - Checklist = all `Card` rows with `set_id`, ordered by a **natural collector-number
    sort** (`_number_sort_key`: leading integer → `(int, "")`; with a non-numeric
    prefix/suffix like `TG01`/`SV01`/`4a` → `(big_int, rest_string)` so numeric cards sort
    before suffixed promos, and suffixed cards sort lexicographically among themselves).
  - Owned set = `{card_id for CollectionItem joined to this set}` (one query).
  - For each **missing** card, `price_service.latest_price(card_id, "normal")` → market
    price or `None`. (Owned cards are not priced here — they're already acquired; pricing
    them is a follow-up and would just add latency. The checklist entry carries
    `owned: bool` and `market: float | None` + `source`/`source_updated_at` staleness for
    priced missing cards.)
  - Summary: `owned`, `checklist_size`, `missing = checklist_size - owned`,
    `pct_complete`, `est_cost_to_complete = sum(market for missing priced)`,
    `unpriced_missing = count(missing where market is None)`. Honest: `est_cost_to_complete`
    is `None` (not `0`) when **all** missing are unpriced; a numeric sum otherwise.
    `unpriced_missing` is always surfaced so the sum is never mistaken for complete.

### 3.2 API routes (no `/api` prefix — frontend `BASE="/api"` Vite-proxied)

- `GET /sets?q=&limit=` → `list[SetProgressOut]`. `q` optional (`min_length=1` when
  present, whitespace-only re-raises 422 — mirrors the sealed deals route). `limit`
  `Query(50, ge=1, le=200)` (174 sets total; default 50 keeps the payload small, the UI
  paginates/scrolls). 422 on out-of-range, mirroring the card-search route's contract.
- `GET /sets/{set_id}` → `SetCompletionOut` (set meta + `cards: list[ChecklistEntryOut]`
  + `summary: CompletionSummaryOut`). 404 when the set id is unknown.

### 3.3 Pydantic models (`catalog/api_models.py`)

`from_attributes=True` where validating from an ORM/dataclass object. `SetProgressOut`,
`SetCompletionOut`, `ChecklistEntryOut` (card_id, name, number, rarity, image_small,
owned, market, source, source_updated_at), `CompletionSummaryOut` (owned, checklist_size,
missing, pct_complete, est_cost_to_complete, unpriced_missing). Nulls (`None`) for
unpriced market — never `0`, never a fabricated price.

### 3.4 Frontend

- **`Sets.tsx`** — the 10th tab. A search box (debounced, mirroring `Browse.tsx`'s state
  machine: idle / searching / results / empty / error) + a list of `SetProgressOut` rows,
  each a glass card with: set name, series + release year, a progress bar (owned /
  checklist_size, `--accent` fill), and `% complete`. Honest 0% for unowned sets (no
  fabricated progress). Clicking a row → `onSelectSet(setId)`.
- **`SetDetail.tsx`** — overlay (AppShell `selectedSet` state + `<AnimatePresence>`,
  mirroring the CardDetail overlay). Header: set name, series, owned / checklist_size,
  `% complete`, **est. cost to complete** (formatMoney — `—` when `None`), and an
  "unpriced: N" muted line when `unpriced_missing > 0`. Checklist grid: one tile per card
  ordered by collector number — image (or placeholder), name, `#number`, rarity, and either
  an **Owned** badge (`--ok`) or a **Missing** label + market price (`formatMoney`, `—` /
  "no market price" when null) with the source + `as of {source_updated_at}` staleness.
  Clicking a tile → `onSelectCard(cardId)` (opens the existing CardDetail overlay, stacked).
- **`api/client.ts`** — `getSets(q?, limit?)` and `getSetCompletion(setId)`.
- **`AppShell.tsx`** — `TabView` gains `"sets"`; `selectedSet` state (string | null) +
  `onSelectSet`/`onCloseSet`; the Sets tab wired in both the desktop sidebar and the mobile
  bottom-nav (10th, after Browse); `<AnimatePresence>` renders `SetDetail` when
  `selectedSet` is set. A new `SetsGlyph` (checklist/grid stroke SVG, same viewBox idiom).
- **Command palette** — add a "Sets" nav command (10th). The `1`–`9` shortcuts do not reach
  it (documented follow-up); it is reachable by click and by palette.

### 3.5 Error handling & honest empty states

- A set with 0 owned → 0% complete, "0 / N owned", est. cost = sum of priced missing (or
  `—` if all unpriced). Never `$0`, never "complete".
- A missing card with no price snapshot → `market: None` → UI shows "no market price" (or
  `—` in the summary line), counted in `unpriced_missing`. Never `$0.00`.
- `/sets` with no `q` returns the newest sets (default limit 50); empty result for a query
  that matches nothing → "No sets found for "{q"}." (mirrors Browse's empty state).
- Backend price resolution uses `PriceService.latest_price` exclusively. No provider is
  constructed for refresh — read-only. No new snapshots written. No `data/` writes.

## 4. Data flow

```
Sets tab (Sets.tsx)
  └─ getSets(q) ──▶ GET /sets ──▶ CompletionService.list_sets
                     (cards + sets + collection, grouped; no price fan-out)
  click set ──▶ onSelectSet(id)
SetDetail.tsx
  └─ getSetCompletion(id) ──▶ GET /sets/{id} ──▶ CompletionService.set_detail
                               (checklist + owned set + latest_price per missing)
  click card ──▶ onSelectCard(cardId) ──▶ CardDetail overlay (existing)
```

## 5. Testing

**Backend (pytest, house style):** `CompletionService` unit tests against an in-memory
session with seeded sets/cards/collection items + a stub `PriceService` (or a real one
against seeded snapshots):
- `list_sets` ordering (release_date desc), the `q` filter (accented name, `func.lower`
  not `ilike`), owned counts grouped correctly, `pct_complete` 0 for an unowned set, no
  divide-by-zero when a set has 0 cards.
- `set_detail` natural sort (numeric `1,2,10` before suffixed `TG01`, `4a`), owned/missing
  flags, `est_cost_to_complete` sums only priced missing, is `None` when all missing are
  unpriced, `unpriced_missing` counts nulls, prices come from `latest_price` (never
  ad-hoc), staleness fields carried.
- Route tests: `GET /sets` 422 on whitespace-only `q` and out-of-range `limit`; `GET
  /sets/{id}` 404 on unknown set; response shapes match the Pydantic models.

**Frontend (vitest, house style — `container.*`, `container.textContent`, never
`.toBeInTheDocument()`):**
- `Sets.tsx`: renders the set list with progress bars; the search state machine
  (idle/searching/empty/error); honest 0% for an unowned set; clicking a row calls
  `onSelectSet`. Fetch stubbed (no network).
- `SetDetail.tsx`: renders the summary KPIs (owned/total, % complete, est. cost `—` when
  null, unpriced count); the checklist ordered by number; Owned vs Missing badges; "no
  market price" for an unpriced missing card; source + `as of` staleness; clicking a tile
  calls `onSelectCard`. Honest empty state when the set has 0 cards.
- `AppShell`/command-palette: the 10th "Sets" tab is reachable; `selectedSet` opens the
  overlay; the one-element `getByRole("button", { name: "Scan" })` invariant still holds
  (the new tab is named "Sets", not "Scan").

## 6. Do-not-break contract

- The 10th nav tab is named **"Sets"** — distinct from the existing 9 accessible names; the
  `getByRole("button", { name: "Scan" })` one-element invariant is preserved (no new "Scan"
  button is added).
- All new CSS classes are distinct (`.sets-*`, `.set-detail-*`, `.checklist-*`); no existing
  rule renamed or removed. The `.bottom-nav` `overflow-x: auto` change is visual-only and
  does not affect any test-queried name/class/aria/`data-label`.
- The studio/centering/etc. frozen strings are untouched. New sub-score/summary strings
  ("owned", "missing", "no market price", "est. cost to complete", "unpriced") are distinct
  from every frozen string.
- Motion wraps existing elements only if added; `SetDetail` overlay uses the same
  `AnimatePresence` + reduced-motion-gated pattern as CardDetail.

## 7. Sacred constraints (held)

- Prices via `PriceService.latest_price` only — never ad-hoc resolution. ✓
- Price staleness surfaced (`source` + `source_updated_at` per priced missing card). ✓
- Honest empty states — `—` / "no market price" / 0%, never `$0`, never fabricated. ✓
- `func.lower(col).like(...)` for set-name search, not `ilike` (accents). ✓
- Read-only: no new tables, no migrations, no snapshots written, no `data/` writes. ✓
- Frontend `BASE="/api"`; routes have no `/api` prefix (Vite-proxied). ✓

## 8. Self-review

- **Placeholder scan:** none — every section is concrete; service/route/model/field names
  are fixed and used consistently.
- **Internal consistency:** `checklist_size` (DB card count) is the completion denominator
  everywhere (list + detail + summary); `total` is reference-only. `est_cost_to_complete`
  is `None` iff all missing unpriced, numeric otherwise; `unpriced_missing` always present.
  Field names match across service → Pydantic → TS.
- **Scope check:** one feature, one plan. Per-variant, cheapest-listing, and shortcut
  follow-ups are explicitly deferred.
- **Ambiguity check:** "owned" = any-variant-owned (made explicit in §2 + §3.1). Sort key
  behavior made explicit in §3.1. Limit default/contract made explicit in §3.2.