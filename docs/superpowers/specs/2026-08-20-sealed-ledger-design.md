# Phase 05d — Sealed Purchase Ledger + Profit Tracker + Google Sheets Sync (OAuth)

> **Status:** design, 2026-08-20. Sibling to `2026-08-19-sealed-product-ev-design.md`
> (Phase 05c, sealed flip-edge deal sniper). Builds on the sealed provider/engine shipped
> in 05c. This phase adds the **reseller leg**: log what you bought, track live profit, and
> mirror the ledger to a Google Sheet via OAuth browser sign-in.

## 1. Goal

Turn the app from a deal-finder into a **reseller's operating console** for sealed product.
A reseller logs boxes/packs they actually bought (query, type, qty, cost/unit, source,
date). The app fetches the current market value per unit (median of recent eBay sold comps,
reusing the 05c sealed sold-comps provider), stores append-only valuations, and computes
live **profit** per purchase and across the book. The whole ledger syncs to a Google Sheet
via **OAuth browser sign-in** (the user's own Google account — no service account).

Honest empty states throughout — no fabricated values, no `$0`, distinct "no purchases" vs
"not yet valued" vs "no eBay key" vs "Google not configured."

## 2. Scope — what ships, what's deferred

**Ships (Part A — local ledger, useful with zero Google setup):**
- Two new tables: `sealed_purchases` (user-editable) + `sealed_valuations` (append-only
  market snapshots, mirroring `PriceSnapshot`'s immutability).
- A `LedgerService` (CRUD + on-demand valuation refresh via the 05c provider + `_median`).
- Read-only profit computation (latest valuation per purchase → profit, profit %, staleness).
- `GET/POST/DELETE /sealed/ledger` + `POST /sealed/ledger/valuate` (+ per-id variant).
- `log-sealed-purchase` / `list-sealed-ledger` / `valuate-sealed-ledger` CLI.
- An 8th "Ledger" frontend tab: log form + ranked ledger + per-row profit + refresh.

**Ships (Part B — Google Sheets sync, activates only once OAuth is configured):**
- A `GoogleSheetsClient` (google-auth-oauthlib InstalledAppFlow + google-api-python-client):
  browser sign-in, local token storage + refresh, full-tab overwrite sync.
- `POST /sealed/ledger/sync` + `sync-sealed-ledger` CLI + a "Sync to Google Sheets" button.
- Honest "not configured" state — local ledger works with zero Google setup; sync is opt-in.

**Deferred (documented follow-ups, NOT this phase):**
- **Rip EV** (expected pull value) — still data-blocked (no pull rates); deferred from 05c.
- **Profit-over-time chart** — the append-only `sealed_valuations` table stores the history
  to enable this later; this phase surfaces only the latest valuation per purchase.
- **Multi-currency** — all costs/values are single-currency (USD) this phase, matching the
  rest of the app; `currency` columns are nullable + passthrough but not converted.
- **Auto-sync on a schedule** — sync is a manual button/CLI this phase; a refresh-on-view
  or cron trigger is a follow-up.

## 3. Why this is the honest shippable unit

The project's load-bearing value is **never confidently wrong / never fake missing data.**
A profit tracker needs only: what you paid (user input) + what it's worth now (median sold
comps — already fetchable from the 05c eBay provider). It needs **no pull rates**, no
grading, no master catalog. Profit is always relative to the latest fetched market and is
surfaced with staleness (`market_fetched_at` + `market_source`) — the user clicks
**Refresh valuations** to update it; we never silently invent a value. The Google sync is
a **mirror** of the local source-of-truth, not a second store — so it degrades to an honest
"not configured" state without breaking the local ledger. This mirrors 05c's
honest-empty-without-key and 05b's degrade-to-noop patterns.

## 4. Architecture

```
reseller logs a purchase (query, type, qty, cost/unit, source, date)
   ↓
SealedPurchase row (sealed_purchases — user-editable, immutable core)
   ↓  (on "Refresh valuations")
LedgerService.refresh_valuation(purchase, provider)
   comps = provider.fetch_sold_listings_by_query(purchase.query, sealed_sold_comp_limit)
   value_per_unit = _median([c.price for c in comps])      # reuse 05c _median
   if value is None: no row inserted (honest: "no recent sold comps")
   else: INSERT SealedValuation(purchase_id, value_per_unit, source="ebay_sold_median",
                                 comp_count, fetched_at=now)   # append-only, never update
   ↓  (on ledger view — read-only)
LedgerService.list_ledger()
   per purchase: latest valuation = max(id) SealedValuation for that purchase_id
   total_cost = qty * cost_per_unit
   total_current_value = value_per_unit * qty     # None if no valuation
   profit = total_current_value - total_cost      # None if no valuation
   profit_pct = profit / total_cost               # None if no valuation or cost==0
   market_fetched_at / market_source from the latest valuation  # staleness
   ↓  (on "Sync to Google Sheets" — opt-in, Part B)
GoogleSheetsClient.sync(rows)  →  clear tab + write header + rows  (full overwrite, idempotent)
```

**Two tables, one user-editable, one append-only.** `sealed_purchases` is user input —
editable/deletable (resellers correct mistakes). `sealed_valuations` is a market snapshot
store — **insert-only, never update** (mirrors `PriceSnapshot`/`GradedPriceSnapshot`'s
immutability; "latest" = max(id) per purchase). This honors the sacred
"price snapshots are immutable (insert, never update)" constraint — the valuation IS the
sealed surface's price snapshot, sourced via the provider, never fabricated.

**Read-only profit.** `list_ledger` never resolves a price ad hoc — it reads the latest
persisted `SealedValuation`. The only live fetch is the explicit **Refresh** action, which
inserts a new snapshot. This is the sealed analogue of
`PriceService.latest_price` / `ListingsService` — not an ad-hoc price resolution.

**Google Sheets is a mirror.** The local DB is the source of truth. Sync reads the ledger
+ latest valuations, builds rows, and **overwrites the target tab** (clear + write) so the
sheet reflects the current truth (including edits/deletes). Append-only sync would not
reflect corrections; full-overwrite is idempotent and honest.

## 5. File structure

**Backend (new):**
- `db/models.py` — `SealedPurchase`, `SealedValuation` (new `Base` subclasses;
  `create_all()` provisions them — no migration entry).
- `sealed/ledger.py` — `LedgerService` (CRUD + `refresh_valuation` + `refresh_all` +
  `list_ledger` + `sync_ledger`) + read-only `LedgerEntry` / `LedgerSummary` dataclasses.
- `sealed/api_models.py` — `SealedPurchaseIn`, `SealedPurchaseOut`, `SealedLedgerEntryOut`,
  `SealedLedgerResponse`, `ValuationRefreshResultOut`, `SheetsSyncResultOut`.
- `sealed/sheets.py` — `GoogleSheetsClient` (OAuth credential lifecycle + sync write).

**Backend (additive edits):**
- `config.py` — `google_sheet_id`, `google_sheet_tab` (default "Sealed Ledger"),
  `google_client_secret_path` / `google_token_path` properties (under `data_dir`).
- `api.py` — `GET/POST/DELETE /sealed/ledger`, `POST /sealed/ledger/valuate`,
  `POST /sealed/ledger/{id}/valuate`, `POST /sealed/ledger/sync`.
- `cli.py` — `log-sealed-purchase`, `list-sealed-ledger`, `valuate-sealed-ledger`,
  `sync-sealed-ledger`.
- `pyproject.toml` — `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.100`.

**Frontend:**
- `api/types.ts` — `SealedPurchase`, `SealedLedgerEntry`, `SealedLedgerResponse`,
  `ValuationRefreshResult`, `SheetsSyncResult`.
- `api/client.ts` — `getSealedLedger`, `logSealedPurchase`, `deleteSealedPurchase`,
  `valuateSealedLedger`, `syncSealedLedger`.
- `components/SealedLedger.tsx` — log form + ledger + per-row profit + refresh + sync.
- `components/AppShell.tsx` — 8th "Ledger" `TabView` + `TabButton` + `LedgerGlyph`.
- `styles.css` — minimal `.ledger-*` additions (reuse `.deal-*` verbatim).

**Site + docs:**
- `site/app/sections/data.ts` — roadmap row 05 subtitle (ledger shipped).
- `AI_CONTEXT.md` — §2 roadmap row 5 + test counts + new §16 writeup.
- `PROJECT.md` — status + roadmap + next-step.
- `docs/superpowers/plans/2026-08-20-sealed-ledger.md` — this phase's task plan.

## 6. Sacred constraints (held)

- **No ad-hoc price resolution.** Profit reads the latest persisted `SealedValuation`
  (the sealed surface's price-snapshot store). The only live fetch is the explicit Refresh
  action, which inserts a new immutable snapshot via the provider + `_median`. Never
  fabricated; never resolved mid-read.
- **Valuations are immutable (insert, never update).** `sealed_valuations` mirrors
  `PriceSnapshot` — append-only; "latest" = max(id) per purchase. Refresh always INSERTs.
- **Purchases are user data (editable/deletable).** Distinct from recognition snapshots.
  Deleting a purchase deletes its valuations (explicit, in-transaction — does not rely on
  a SQLite FK-cascade pragma).
- **Honest empty states — no `$0`, no fabricated value.** `value_per_unit` / `profit` /
  `profit_pct` are null when no valuation exists; the UI shows `—` via `formatMoney(null)`
  and "Not yet valued — click Refresh." Distinct flags: `no purchases` vs
  `listings_unavailable` (no eBay key → can't refresh) vs `not yet valued` (has purchase,
  no valuation) vs `sync not configured` (no OAuth).
- **Degrade to no-op, never raise.** The provider degrades to `[]` (05c). No eBay key →
  no valuation inserted (honest), never an error. Google not configured → sync returns
  `synced=False, reason="not_configured"`, never raises.
- **Always surface staleness.** Each ledger entry carries `market_fetched_at` +
  `market_source` from its latest valuation. The sheet includes a "Valued At" column.
- **No `data/` deletion.** The 105-scan baseline + FAISS index + SQLite db untouched.
  New tables are additive. The OAuth token + client secret are stored under `data/`
  (gitignored) — never committed.
- `func.lower().like` n/a (no DB text search). `UtcDateTime` for `bought_at` / `fetched_at`
  / `created_at` (tz-aware). No `""` sentinel needed (valuations have no unique-constraint
  column that may lack a source timestamp).

## 7. The profit math (exact)

```
# per purchase, read-only (LedgerService.list_ledger):
latest = max(valuations for purchase_id, by id)        # None if none
total_cost          = quantity * cost_per_unit
value_per_unit      = latest.value_per_unit if latest else None
total_current_value = value_per_unit * quantity        if value_per_unit is not None else None
profit              = total_current_value - total_cost if total_current_value is not None else None
profit_pct          = profit / total_cost              if profit is not None and total_cost > 0 else None
market_fetched_at   = latest.fetched_at if latest else None
market_source       = latest.source     if latest else None

# refresh (LedgerService.refresh_valuation) — the only write path for valuations:
comps        = provider.fetch_sold_listings_by_query(purchase.query, sealed_sold_comp_limit)
comp_prices  = [c.price for c in comps if c.price is not None]
value        = _median(comp_prices)                    # reuse sealed/engine._median
if value is None: return None                          # no comps → no snapshot, honest
INSERT SealedValuation(purchase_id, value_per_unit=value, source="ebay_sold_median",
                       comp_count=len(comp_prices), fetched_at=now)
```

`value_per_unit` is a **median** (robust to one outlier comp), identical to 05c's
`sealed_market`. Profit is **gross** (selling fees not subtracted) — the same framing as
the 05c flip-edge; the UI says so. Profit is an **indicative live figure** ("as of
`market_fetched_at`"), not a realized sale — the reseller hasn't sold yet.

## 8. Google Sheets sync (OAuth) — exact

**Auth:** `google-auth-oauthlib` `InstalledAppFlow` (Desktop-app client secret). Scope:
`https://www.googleapis.com/auth/spreadsheets`. Flow: load token from
`data/google_token.json`; if missing/invalid and refreshable → refresh; else run
`flow.run_local_server(port=0)` (opens the user's browser, binds a local port, captures the
redirect) → save token to `data/google_token.json`. The client secret is the user's
downloaded OAuth 2.0 Client ID (Desktop type) placed at `data/credentials.json`.

**Config:** `CARDPLATFORM_GOOGLE_SHEET_ID` (the spreadsheet ID from the sheet URL),
`CARDPLATFORM_GOOGLE_SHEET_TAB` (default "Sealed Ledger"). Both via the `settings` singleton
(env prefix `CARDPLATFORM_`), like `CARDPLATFORM_LISTINGS_API_KEY`.

**Sync:** `GoogleSheetsClient.sync(rows)`:
1. `is_configured()` — False iff `data/credentials.json` missing OR `google_sheet_id` unset
   → return `synced=False, reason="not_configured"` (no network call, no raise).
2. Build the `sheets(v4)` service with the credentials.
3. Clear the tab range `{tab}!A1:Z10000` (`values().clear`) — full overwrite is idempotent
   and reflects edits/deletes.
4. `values().update(range="{tab}!A1", valueInputOption="RAW")` with header + one row per
   ledger entry. Columns: Date, Product, Type, Qty, Cost/Unit, Total Cost, Market/Unit,
   Total Value, Profit, Profit %, Valued At, Source, Bought From, Notes. Nulls → empty
   string (the sheet shows blanks, not `$0`).
5. Return `synced=True, rows=<n>`.

**Setup story for the user (documented in AI_CONTEXT §16 + UI/CLI hints):**
create a Google Cloud OAuth 2.0 Client ID (Desktop app), download the JSON as
`data/credentials.json`, create a (possibly empty) Google Sheet, copy its ID from the URL
into `CARDPLATFORM_GOOGLE_SHEET_ID`, run sync once (browser consent → token saved), done.

**Token safety:** `data/` is gitignored (`.gitignore:51`) and `credentials.json` is
gitignored anywhere (`.gitignore:8`) — confirmed. The token (with refresh token) and the
client secret are never committed.

## 9. Open questions (auto-mode defaults)

- **Profit = gross, market = median of sold comps** — reuses 05c's sealed_market exactly;
  no selling fees, no lowest-active-listing reference. Median is robust.
- **Valuation history is stored but only latest is surfaced** — the append-only table
  enables a profit-over-time chart later; this phase shows latest-only (with staleness).
- **Sync = full-tab overwrite** (clear + write), not append — reflects edits/deletes
  idempotently. A "sync history" / append mode is a follow-up.
- **`POST /sealed/ledger/valuate` refreshes ALL purchases** (the common case); a
  `POST /sealed/ledger/{id}/valuate` per-row variant also ships. Refresh requires the eBay
  key (reuses `CARDPLATFORM_LISTINGS_API_KEY`); no key → 0 valued, `skipped_no_key=True`.
- **8th bottom-nav tab "Ledger"** — distinct surface (inventory, not deal-finding); a tab
  beats a Sealed sub-panel (the established "distinct surface = tab" pattern). 8 flex:1
  buttons is tight on narrow screens — flagged as a known minor follow-up (no blocker).
- **OAuth = browser sign-in, user's own account** (user-chosen over service account / Apps
  Script). Token + secret under `data/` (gitignored). `flow.run_local_server(port=0)`
  requires a desktop/browser — this is a local-first app, not a headless server.