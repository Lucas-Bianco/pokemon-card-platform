# Phase 05b — Deal Alerts + eBay Sold-Comps Evidence (Design)

> **Status:** Design. Auto mode — surfaced for visibility, not blocking on approval.
> **Date:** 2026-08-04
> **Repo:** `C:\ClaudeKnowledge` (github.com/Lucas-Bianco/pokemon-card-platform)
> **Predecessor:** Phase 05 deal-sniper (shipped 2026-08-03) — read-only `DealEngine`, eBay Finding API adapter, 6th Deals tab, scroll-animated site section. 462 backend + 96 frontend tests green.

## Goal

Two legs that make the deal-sniper *push* instead of *pull*, and back the raw market price with real sale evidence:

1. **Deal alerts** — compose the Phase 3c `AlertEngine` with the Phase 05 read-only `DealEngine` so that a *new* active listing which clears the rip/flip thresholds fires an alert. Reuses the 3c poll loop, notification channels, and the per-watch `last_seen_listing_ids` baseline dedupe.
2. **eBay sold-comps evidence** — fetch the 3 most recent eBay **sold** listings for a card (Finding API `findCompletedItems`, `SoldItemsOnly=true`) and surface them in the Deal / price UI as evidence backing the raw market price ("market $120 because these 3 just sold at $118 / $121 / $119").

Both legs are additive — no change to recognition, raw prices, the sacred snapshot-immutable constraint, or the 105 real scans.

## Standing directive & sacred constraints (in force)

- Work in **auto mode** — proceed autonomously, no per-step check-ins. Only edit/delete files inside `C:\ClaudeKnowledge`. **Commit all new code to GitHub** (push `origin/main`; solo repo). **Ask before destructive/irreversible commands.** Never delete anything under `data/`.
- Python 3.12 **only** via `backend/.venv` (system Python is 3.14, lacks ML wheels).
- Never resolve "the latest price" ad-hoc — use `PriceService.latest_price` / `GradedPriceService.latest_graded` / `ListingsService.latest_listings` / `DealEngine.assess`.
- Snapshots are immutable (insert, never update). **Sold comps are NOT persisted** — on-demand evidence only (no `SoldCompSnapshot` table, no snapshot writes).
- Surface price/listing staleness (`source` + `source_updated_at`/`fetched_at`).
- Honest empty states — em dash / "no recent sold comps", never `$0`, never fabricate. Providers degrade to `[]`, never raise.
- `func.lower(col).like(...)` not `ilike` (accents). `UtcDateTime` TypeDecorator for tz-aware columns. `""` sentinel for unique-constraint cols that may lack a source timestamp.
- Match surrounding code style; keep `AI_CONTEXT.md` current.

## Leg 1 — Deal alerts

### Watch model (no schema change)

A `deal` watch fits the existing `Watch` model exactly — **no new columns, no migration**:

- `alert_type = "deal"`
- `card_id` + `variant` set (variant defaults to `""`)
- `target_price = None`, `drop_at = None`
- Unique key `(card_id, variant, "deal", None, None)` — one deal watch per card/variant
- `last_seen_listing_ids` (existing JSON String column) carries the baseline dedupe set

Thresholds are the **global** `deal_rip_min_abs` / `deal_rip_min_pct` / `deal_flip_min_abs` settings (already read by `DealEngine`); a deal watch stores no per-watch thresholds.

### AlertEngine changes

`backend/src/cardplatform/alerts/engine.py`:

- Constructor gains an optional collaborator:
  ```python
  def __init__(self, session, listings_service, notifier, settings, clock, *, deal_engine=None):
      ...
      self._deal_engine = deal_engine  # DealEngine | None
  ```
  Defaulting to `None` keeps existing callers (and the 3c tests that construct `AlertEngine` without it) green — a missing deal engine simply means deal watches never fire.

- `_eval` dispatch gains one branch:
  ```python
  if atype == "deal": return self._eval_deal(w, now)
  ```

- New `_eval_deal(w, now)`, mirroring `_eval_new_listing`'s baseline-dedupe pattern (lines ~225-253 of the current engine):
  - If `self._deal_engine is None`: `log.info(...)` and `return 0` (graceful — no crash).
  - `assessments = self._deal_engine.assess(w.card_id, w.variant)` (read-only; no snapshot writes).
  - `curr_deal_ids` = `[a.listing_id for a in assessments if a.is_rip or a.is_flip]` (set).
  - Load `prev_ids` from `w.last_seen_listing_ids` (JSON-decoded list, or `[]` if null/empty).
  - **First-poll rule (sacred, mirrors new_listing):** if `prev_ids == []` (no baseline yet), write `curr_deal_ids` as the baseline, return 0 — never fire on the first poll.
  - `new_ids = curr_deal_ids - prev_ids`. For each `listing_id` in `new_ids`, find its `DealAssessment` and `_fire(w, message, context)` with a deal-specific message + context.
  - Persist `list(curr_deal_ids)` back to `w.last_seen_listing_ids` (JSON string), even if empty — the baseline must advance so a listing that *stops* being a deal doesn't re-fire.
  - Return the count fired.
  - Never raises out of `_eval_deal` (the per-watch SAVEPOINT isolation in the existing `_run` loop already contains any exception; but `_eval_deal` itself catches nothing extra beyond what `DealEngine.assess` already guarantees — `assess` never raises per Phase 05).

- `_fire` is reused unchanged (it inserts the immutable `AlertEvent` row, flushes, dispatches the notifier, swallows notifier failures).

- **Alert context** (JSON on `AlertEvent.context`):
  ```json
  {
    "listing_id": "...", "url": "...", "listing_price": 40.0, "currency": "USD",
    "condition": "...", "rip_edge": 12.0, "flip_edge_to_10": 95.0,
    "is_rip": true, "is_flip": false, "deal_score": 95.0,
    "raw_market": {"price": 52.0, "source": "tcgplayer", "source_updated_at": "2026/07/30"}
  }
  ```
- **Message** (one line, honest, no "guaranteed arbitrage"):
  - rip: `"Deal on Charizard #4 — listing $40.00 vs market $52.00 (RIP edge $12.00). Verify before buying."`
  - flip: `"Deal on Charizard #4 — listing $40.00, PSA-10 flip spread $95.00 after grading. Verify before buying."`
  - both: lead with the larger of rip/flip.

### Watchlist API validation

`backend/src/cardplatform/api.py`:

- `_ALERT_TYPES` becomes `{"restock", "new_listing", "price_target", "auction_ending", "drop_time", "deal"}`.
- Add a 422 rule: if `alert_type == "deal"` and `payload.card_id is None` → 422 `detail="card_id is required for alert_type 'deal'"`. `deal` requires no `target_price` / `drop_at` (the existing price_target/drop_time rules already gate only their own types). `variant` defaults to `""`.

### Poll loop + CLI wiring

- `api.py` `_poll_loop` (and the `check-alerts` path if separate): construct `DealEngine(session, settings, price_service, graded_service, listings_service)` and pass `deal_engine=...` into `AlertEngine(...)`. The existing `EbayListingsProvider`-wired `ListingsService` is shared — `DealEngine` already takes the same `listings_service`.
- `cli.py` `check_alerts`: same injection. `python -m cardplatform.cli check-alerts` now evaluates deal watches.

## Leg 2 — eBay sold-comps evidence

### Deprecation caveat (documented, not blocking)

eBay **deprecated `findCompletedItems` on 2020-10-15** in favor of the Marketplace Insights API (Limited Release — needs approval, not viable for a solo free-tier app). The deprecated endpoint **still responds for free App IDs today**. The adapter degrades to `[]` on any failure (no key, transport error, retirement, unexpected shape), and the UI shows an honest "recent sold comps unavailable" — so shipping behind `findCompletedItems` is safe: the evidence surfaces when eBay cooperates, honest-empty when it doesn't. A future upgrade to Marketplace Insights (if/when approved) is a documented follow-up, not this phase. **`SERVICE-VERSION=1.13.0` is required** — the legacy `1.0.0` returns `sellingState="Ended"` for sold items (eBay bug #185); `1.13.0` returns the correct `"EndedWithSales"`.

### Provider method

`backend/src/cardplatform/prices/ebay_listings.py` (the T1 Finding API adapter):

- New dataclass `SoldComp` (in `prices/listings_provider.py` alongside `ListingQuote`):
  ```python
  @dataclass(frozen=True, slots=True)
  class SoldComp:
      card_id: str
      variant: str
      listing_id: str
      title: str | None
      price: float
      currency: str | None
      url: str | None
      condition: str | None
      sold_at: datetime | None   # tz-aware UTC, from listingInfo.endTime
      source: str = "ebay"
  ```

- `EbayListingsProvider.fetch_sold_listings(card_id, variant, limit=3) -> list[SoldComp]`:
  - Same no-key → `[]` short-circuit as `fetch_listings` (never touches the network without a key).
  - `query = self._build_query(card_id)` (reuse — name + number, no set name).
  - `payload = self._search_completed(query, limit)` — a sibling of `_search` that sets:
    - `OPERATION-NAME=findCompletedItems`
    - `SERVICE-VERSION=1.13.0` (the bug gotcha)
    - `itemFilter(0).name=SoldItemsOnly`, `itemFilter(0).value=true`
    - `sortOrder=EndTimeSoonest` (most-recently-ended first)
    - `paginationInput.entriesPerPage=str(limit)` (default 3)
    - identical retry/terminal/degrade discipline (404/401 terminal one attempt; 5xx/429/transport retry then `None`; bad JSON terminal; `RetryError` → `None`). Refactor the retry decorator into a shared helper or duplicate it — match surrounding style, but do NOT regress `fetch_listings`.
  - `return self._parse_completed(card_id, variant, payload)` wrapped in the same `try/except (TypeError, ValueError, KeyError, AttributeError)` → `[]`.

- `_parse_completed(card_id, variant, payload)` (static, mirrors `_parse`):
  - Top-level key is `findCompletedItemsResponse` (not `findItemsByKeywordsResponse`).
  - Reuse the `_first(node, key)` single-element-array unwrap.
  - For each `item`:
    - `listing_id = _first(item, "itemId")`; skip if missing (never fabricate).
    - `selling = _first(item, "sellingStatus")`; `state = _first(selling, "sellingState")`. **Skip the item unless `state == "EndedWithSales"`** — `EndedWithoutSales` and anything else are NOT sold comps; never fabricate a sale. (This is the whole point of `SERVICE-VERSION=1.13.0`.)
    - `price`/`currency` from `sellingStatus.currentPrice` exactly as in `_parse`; **skip if `price is None`** (sacred never-fabricate).
    - `sold_at = _parse_iso(_first(listing_info, "endTime"))` (the sale close — `endTime` IS meaningful for completed listings, unlike active fixed-price).
    - `url`, `condition`, `title` as in `_parse`.
    - Append `SoldComp(...)`.
  - Return the list (already capped by `entriesPerPage`; slice to `limit` defensively).

### API endpoint

`backend/src/cardplatform/api.py`:

- `GET /cards/{card_id}/sold-comps?variant=&limit=3`:
  - `variant` defaults to `""`; `limit` clamped to `[1, 10]`, default 3.
  - Construct `EbayListingsProvider(catalog=_catalog_lookup(session))` (same helper the deals/listings endpoints use) and call `fetch_sold_listings(card_id, variant, limit)`.
  - Response (`SoldCompsResponse`):
    ```json
    {
      "card_id": "base1-4", "variant": "",
      "sold_comps": [ { "listing_id": "...", "title": "...", "price": 118.0, "currency": "USD",
                        "url": "...", "condition": "...", "sold_at": "2026-07-30T18:30:00Z",
                        "source": "ebay" } ],
      "sold_comps_unavailable": false,
      "sold_comps_empty": false
    }
    ```
  - `sold_comps_unavailable` = `True` when no `CARDPLATFORM_LISTINGS_API_KEY` is configured (the provider returned `[]` without fetching) **or** the fetch failed/degraded. `sold_comps_empty` = `True` when the fetch succeeded but found no sold comps. Both false when comps are returned. (Mirrors the `listings_unavailable` / `listings_empty` flags on the deals/listings endpoints — the established honest-empty contract.)
  - Pydantic v2 models in a new `prices/api_models.py` (or extend `deals/api_models.py` — match surrounding layout). `SoldCompOut` with `model_config = ConfigDict(from_attributes=True)`.
  - No persistence — on-demand read. No snapshot writes. `sold_at` serialized as ISO via the existing `UtcDateTime`/datetime JSON convention.

### Frontend evidence

`frontend/src/`:

- `api/types.ts`: `SoldComp`, `SoldCompsResponse` types; extend `AlertType` union with `"deal"`.
- `api/client.ts`: `getSoldComps(cardId, variant, limit=3)`; add `"deal"` to the `ALERT_TYPES` array used by the watch sheet.
- New `components/SoldComps.tsx` — a compact "Recent sold (eBay)" evidence block. Up to 3 rows: `formatMoney(price)` + relative time of `sold_at` (reuse `relativeTime` from `lib/time.ts`) + condition + outbound `url`. Honest empty states:
  - `sold_comps_unavailable` → "Recent sold comps unavailable — set a listings source key to show eBay sale evidence." (never a fake price)
  - `sold_comps_empty` → "No recent eBay sold comps found for this card."
  - Caption: "Sold comps are evidence backing the market price, not a price target."
- `components/CardDetail.tsx`: render `<SoldComps>` under the market-price block (evidence for the raw price). Stub in `__tests__/CardDetail.test.tsx` (`stubFetch` gains a `soldComps` branch matching `/sold-comps`).
- `components/Deals.tsx`: render `<SoldComps>` once near the top of the deals view as shared evidence backing the raw market prices in the feed.

### Frontend deal-alert affordance

- `components/WatchCardSheet.tsx`: add a 6th chip to `TYPE_INFO`:
  ```ts
  deal: { label: "Deal", description: "Ping me when a new listing clears the RIP/flip deal thresholds.", needsCard: true, needsListings: true }
  ```
  No conditional fields (no target price / drop time). Submit sends `alert_type: "deal"`.
- `components/AlertsFeed.tsx`: add `{ value: "deal", label: "Deal" }` to the filter chips and `deal: "💸"` to `ICON`; the existing `ICON[ev.alert_type]` + filter render then handle deal events with no further change. A deal alert row's message already carries the listing url in `context` — render the existing message text (the backend composes it).
- `components/More.tsx` watch-list rendering already does `w.alert_type.replace("_", " ")` — `"deal"` renders as "deal"; optionally title-case for polish (match surrounding style).

## Out of scope

- Persisting sold comps to a `SoldCompSnapshot` table — they are on-demand evidence, not a price source. (A future phase could persist for a sold-comp price history, but that's a separate sacred-snapshot decision.)
- Per-watch deal thresholds — deal watches reuse the global `deal_*` settings.
- Marketplace Insights API migration — documented follow-up, not this phase.
- Surfacing sold comps in the deployed Next.js *site* — the site stays a marketing surface; the evidence is an app feature. (The site's Deals section caption gets a one-line mention only if cheap.)

## Verification (end-to-end)

- **Backend:** `backend/.venv/Scripts/python -m pytest` — 462 → N, all green. New tests: provider `fetch_sold_listings` degrades to [] w/o key, parses sold comps, skips `EndedWithoutSales`, skips price-less items, caps to limit; endpoint honest flags (unavailable/empty/populated); `_eval_deal` first-poll-never-fires, fires on new deal listings only, advances baseline, no-op when `deal_engine=None`; watchlist 422 for `deal` w/o card_id. Manual: `python -m cardplatform.cli check-alerts` with a deal watch + a key set → an `AlertEvent` row appears for a new rip/flip listing; `GET /cards/base1-4/sold-comps?variant=` returns up to 3 sold comps (or honest flags).
- **Frontend:** `npm --prefix frontend test -- --run` — 96 → N green; `npm --prefix frontend run build` clean. Manual smoke (backend :8000, frontend :5173): open a card → "Recent sold (eBay)" block renders comps or an honest empty state; create a Deal watch in the sheet → it appears in More → watches; a deal alert renders in AlertsFeed with the 💸 icon.
- **Sacred constraints:** no ad-hoc price resolution (only `DealEngine.assess` / `PriceService.latest_price`); no snapshot writes for sold comps; staleness surfaced (`sold_at`); honest empty states unchanged; no `data/` deletion; snapshots still immutable.

## Execution

Subagent-driven (fresh implementer per task, TDD, inline spec + quality reviews to conserve budget — the established Phase 05 pattern). Task sketch (finalized in the implementation plan):

1. Sold-comps provider method + `SoldComp` dataclass + tests.
2. Sold-comps API endpoint + Pydantic models + tests.
3. Frontend `SoldComps.tsx` evidence block + CardDetail/Deals wiring + tests.
4. Deal-alert backend: `_eval_deal` + `AlertEngine.deal_engine` injection + watchlist `_ALERT_TYPES`/422 + tests.
5. Wire `DealEngine` into `AlertEngine` in `api.py` poll loop + `cli.py` check-alerts + tests.
6. Frontend deal alert: WatchCardSheet `deal` chip + AlertsFeed filter/icon + types/client + tests.
7. Docs (`AI_CONTEXT.md`, `PROJECT.md`) + optional site caption; integrate, verify (full test suite + builds), push `origin/main`, deploy GitHub Pages, confirm `built`.

Auto mode: proceed through all tasks without per-step check-ins; commit per task; push + deploy at the end.