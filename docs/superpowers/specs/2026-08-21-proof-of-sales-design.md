# Proof of Sales — Design Spec

> Status: design approved 2026-08-21 by direction choice ("proof-of-sales first, then A") + auto-mode.
> Implements roadmap row 16. Reuses Phase 05b card sold-comps + 05c sealed sold-comps plumbing.

## Goal

Every market price in the app is accompanied by **proven sales** — actual eBay sold
transactions (date, price, condition, listing title, source link) — so the user sees that real
people paid real money, not a retailer's listed estimate. This is the project's honest
differentiator: "99% of price apps assert a number and never prove anyone paid it." We prove it,
or we honestly say we can't.

## The honesty distinction (the whole feature)

There are two distinct price concepts in the data model, and the UI must never collapse them:

- **Market (listed)** — `PriceService.latest_price` / `GradedPriceService.latest_graded`: a
  tcgplayer / pokemontcg / cardmarket / pkmnprices **listed retail estimate**. An asking price, not
  a sale. Shown with `source` + `source_updated_at` (staleness surfaced — sacred constraint).
- **Proven sales** — eBay `findCompletedItems` with the `EndedWithSales` gate
  (`SERVICE-VERSION=1.13.0`, already solved in `prices/ebay_listings.py`): **actual
  transactions**. On-demand, never persisted (mirrors the existing card sold-comps discipline).

The UI labels both explicitly. Both are sourced + timestamped. Never `$0`. Honest empty state
when 0 comps: "No recent proven sales found." Providers degrade to `[]`, never raise (sacred).

## Existing plumbing (reuse — already production-shaped)

- **Card sold-comps:** `EbayListingsProvider.fetch_sold_listings(card_id, variant, limit=3)`
  (`prices/ebay_listings.py:97`) → `GET /cards/{card_id}/sold-comps` (`api.py:1440`) →
  `SoldCompsResponse{comps, sold_comps_unavailable, sold_comps_empty}` (`sold_comps_api_models.py`)
  → frontend `SoldComps.tsx` + `getSoldComps`. Mounted on `CardDetail`. Limit clamp 10 (`api.py:1461`).
- **Sealed sold-comps (median only today):** `fetch_sold_listings_by_query(query)`
  (`ebay_listings.py:142`) → `SealedDealEngine.assess` computes `sealed_market = median(sold comps)`
  (`sealed/engine.py:100`); exposed via `GET /sealed/deals` and persisted as `SealedValuation`
  (`source="ebay_sold_median"`, `comp_count`) by `LedgerService.refresh_valuation`. The individual
  `SealedSoldComp` list is **not** exposed as a route today.
- **Honest-empty flag pattern:** `*_unavailable` (no listings key) vs `*_empty` (key set, 0 comps) —
  established and consistent across `SoldCompsResponse`, `SealedDealsResponse`, `ValuationRefreshResult`.
  Copy it for any new surface.

## Scope (what we build)

### Backend

1. **NEW endpoint `GET /sealed/sold-comps`** — query-keyed individual sealed sold-comps.
   - Reuses `fetch_sold_listings_by_query(query, limit)`.
   - Returns `SealedSoldCompsResponse{comps: [SealedSoldCompOut], sold_comps_unavailable, sold_comps_empty}`.
   - `q: str` `Query(min_length=2)` — whitespace-only → 422 (mirror `/sealed/deals`).
   - `limit: int = Query(6, ge=1, le=10)` — clamp like card sold-comps.
   - No DB dep (on-demand evidence, like card sold-comps). No persistence.
   - Wire model `SealedSoldCompOut` + `SealedSoldCompsResponse` in `sealed/api_models.py`
     (`from_attributes=True`). Mirror `SoldCompOut`/`SoldCompsResponse` field-for-field.

2. **No change** to card sold-comps endpoint (already correct). Optionally raise the default
   `limit` from 3 → 6 in the *frontend* call only (backend already clamps to 10); do not change
   the backend default to avoid breaking existing consumers.

### Frontend

3. **NEW `ProofOfSales.tsx`** — reusable evidence block. Props: a fetcher (or `cardId+variant` /
   `query`) + a heading. Renders:
   - A header "Proven sales" + the one-line listed-vs-proven caveat
     ("Market price is a listed estimate; these are actual eBay sales.").
   - Loading / `unavailable` ("Set a listings source key to see proven sales") / `empty`
     ("No recent proven sales found on eBay.") / list states.
   - Each comp: date (`sold_at`), price (`formatMoney`), condition, title, and an external link
     to the eBay listing (`url`, opens new tab, `rel="noopener"`).
   - Honest empty states never show `$0`.
   - Reuse/additive CSS (`.proof-*`), glass surface matching `.sold-comps-*`/`.deal-*` idiom.

4. **Wire into `ScanResult`** (cards) — render `ProofOfSales` next to `PriceLine` when a card is
   recognized. Card-gated (no card → no proof). This is the headline surface: scan → see the
   price **and** its proof.

5. **Wire into `SealedLedger`** (sealed, per-purchase) — a "Show proven sales" toggle per row that
   fetches `GET /sealed/sold-comps?q=<purchase query>` and renders `ProofOfSales`.

6. **Wire into `SealedDeals`** (sealed, per-deal) — each deal row can expand to show its proven
   sales via the same endpoint.

7. **Types + client:** add `SealedSoldComp`, `SealedSoldCompsResponse` to `api/types.ts`;
   `getSealedSoldComps(query, limit?)` to `api/client.ts` (throws on non-ok, like
   `getSealedDeals`).

### Do-not-break contract

- Additive `.proof-*` classes; no existing class/input[name]/aria-label/button-name/empty-state
  string renamed. Existing `SoldComps.tsx` on `CardDetail` keeps working — `ProofOfSales` is a
  new component, `SoldComps` is not renamed (we may have `ProofOfSales` wrap/replace it on
  `ScanResult` only; `CardDetail`'s `SoldComps` stays).
- The one-element `getByRole("button",{name:"Scan"})` invariant preserved.
- BulkScan / ScanResultGrading test stubs get a `/sealed/sold-comps` branch ONLY if those tests
  mount a sealed surface (they don't) — so no stub change needed there; the card sold-comps
  stub already exists where relevant.

## Tests (TDD)

- **Backend:** `GET /sealed/sold-comps` — happy (returns comps), `sold_comps_unavailable` (no
  key), `sold_comps_empty` (key set, 0 comps), blank/whitespace `q` → 422, `limit` out of range
  → 422, unknown query → empty (not error). Reuse the ebay provider test-stub pattern from
  `test_sealed_deals_api.py` / `test_sold_comps_api.py`.
- **Frontend:** `ProofOfSales.test.tsx` — renders comps (date/price/link), `unavailable` state,
  `empty` state, listed-vs-proven caveat present, link has `rel="noopener"` + opens new tab.
  Wiring tests: `ScanResult` shows proof when card present (extend `ScanResultGrading.test.tsx`
  stub with `/sold-comps` branch — it may already have one; verify), `SealedLedger` "Show proven
  sales" toggle fetches + renders.

## Out of scope (deferred, recorded)

- Proof wiring on `PortfolioView`, `Dashboard`, `SetDetail`, `Deals.raw_market`,
  `GradingUpside` (follow-up — the per-card plumbing already exists).
- Sold-comp **persistence / trending** (new table mirroring `SealedValuation` for history of
  sold-comps medians over time) — deferred; on-demand is honest enough for v1.
- Deal-alert gating on sold-comps (alerts engine currently uses active listings + retail market).
- Higher per-card limit / "view all" route (backend already accepts up to 10; frontend can ask).

## Sacred constraints held

- `latest_price` / `latest_graded` / `ListingsService` used as-is; never resolve price ad-hoc.
- Sold-comps are on-demand evidence, never fabricated; `EndedWithSales` gate preserved.
- Honest empty states (`*_unavailable` / `*_empty`) reused; never `$0`.
- Providers degrade to `[]`, never raise. `func.lower().like()` n/a (query-keyed). Staleness
  surfaced (`source` + `sold_at`). No `data/` writes. 105-scan baseline untouched (zero
  recognition/detection code changed).

## Build order

1. Backend: `GET /sealed/sold-comps` + wire models + tests (TDD).
2. Frontend types + `getSealedSoldComps` client fn + test.
3. `ProofOfSales` component + tests.
4. Wire into `ScanResult` (cards) + test.
5. Wire into `SealedLedger` + `SealedDeals` (sealed) + tests.
6. Full suite: `pytest -q` (backend) + `npm --prefix frontend test -- --run` (frontend) + build.
7. Commit + push `origin/main`.
8. Run dev server (backend + frontend `--host`) so the user can test on phone.