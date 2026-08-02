# Phase 3c — Alerts: Watchlist + Restock/Price/Drop/Auction notifications + CollectorVault-style UI

**Status:** Design (brainstormed 2026-08-02). Predecessor: Phase 3b (grading data infrastructure, shipped).
**Roadmap mapping:** ships the user-facing head of Phase 05 (Deal sniper & sealed EV) — the watchlist + notifications leg — without the rip-vs-flip math, which remains planned.

## What and why

The platform can already scan, recognize, price, and (as of 3b) show a grading-upside spread and
self-annotate grades. What it cannot do is **tell you when to act**: when a card restocks, hits your
price, an auction is about to end, or a Pokémon Center vending machine is about to drop.

This phase adds a **CCN-style watchlist + notification system** as the app's new home surface, plus a
**CollectorVault-style UI/nav polish** across the existing scanner, portfolio, and a new browse + card
detail. The chosen app shell is **B — Alerts-first**: the home screen *is* the alert feed.

**Marketing/sales framing (the product lens for this phase):** the value proposition is "your personal
card-market radar" — get pinged the moment a card restocks, hits your price, or a vending machine drops,
across eBay listings, auctions, and scheduled drops. Every surface sells the capability honestly: no
fake alerts, no fabricated listings, and a clear "set a listings key / enable push" nudge when a channel
isn't configured. The onboarding magic moment is camera-first (scan before any setup, Collectr-style),
with "Watch this card" surfaced contextually right after a successful scan.

## Locked decisions (from brainstorm)

- **App shell:** B — Alerts-first. Bottom nav (PWA standalone, 5 tabs): **Scan · Vault · Alerts · Browse · More**. Alerts is the default home and carries an unread badge.
- **Alert types (five):** restock (back in stock), new listing appears, auction ending soon, Pokémon Vending Machine drop times, **and price target hit** (a card's lowest listing/market price drops to or below a target you set). The first four were explicitly chosen in brainstorm; price target is included because the chosen app shell (B) features a price-target alert front-and-center in its feed mockup — it's the natural fifth type and a core CCN/Collector capability. (Flagged for the user at spec review: drop it if unwanted.)
- **Delivery channels (all three):** in-app center + badge; web push (PWA, VAPID); email (SMTP). Each channel degrades gracefully when unconfigured — never silently fails, never fabricates a send.
- **Scope:** Alerts-first. Deal-sniper math (rip-vs-flip, sealed EV) and set-completion optimizer remain planned — not in this phase.

## Architecture (committed)

Reuse the project's sacred patterns verbatim: swappable provider protocol; immutable snapshots;
`func.lower(...).like` for text search; honest empty states; providers env-keyed and **degrading to `[]`
without ever raising**; additive migrations via `db/migrations.py` `run_migrations(engine)`; `UtcDateTime`
for all tz-aware columns; the empty-string sentinel for unique-constraint columns that may lack a
source timestamp (NULLs are distinct under a unique constraint; `""` collides).

### New data model (additive; existing rows untouched)

All in `db/models.py`, created by `Base.metadata.create_all()` for new tables; nullable columns on
existing tables added by `run_migrations` PRAGMA-check-then-ALTER. **No change to `PriceSnapshot`,
`GradedPriceSnapshot`, `ScanLog` (beyond what 3b already added), `CollectionItem`, or catalog tables.**

1. **`Watch`** (`watchlist`) — one alert rule the user wants tracked.
   - `id` (int pk autoincrement)
   - `card_id: str | None` (FK cards.id, index; nullable — a vending-machine drop watch may target a product/line, not a specific card)
   - `subject_label: str | None` (human label when `card_id` is null, e.g. "Pokémon Center vending machine — promo tin")
   - `variant: str | None` (nullable, same honest-absence convention as `GradingLabel.variant`)
   - `alert_type: str` (index) — `"restock" | "new_listing" | "price_target" | "auction_ending" | "drop_time"`
   - `target_price: float | None` (for `price_target`)
   - `drop_at: datetime | None` (UtcDateTime; for `drop_time`)
   - `lead_time_min: int | None` (for `drop_time`: fire this many minutes before `drop_at`; default 0 = fire at the drop)
   - `auction_window_min: int | None` (for `auction_ending`; default 30)
   - `active: bool` (default true; pause/resume)
   - `last_seen_listing_ids: str | None` (JSON-encoded list of provider listing ids seen on the last poll; the idempotency cursor for `restock` / `new_listing`)
   - `last_fired_at: datetime | None` (UtcDateTime; cooldown cursor for `price_target` / `drop_time`)
   - `created_at: datetime` (UtcDateTime, default `_utcnow`)
   - Unique constraint `uq_watch` on `(card_id, variant, alert_type, target_price, drop_at)` to prevent exact-duplicate rules. (NULL columns would defeat this under SQLite's NULL-distinct rule, so store the nullable numeric/time fields with a sentinel where needed — see migration note — OR accept that duplicates across NULLs are allowed and dedupe in the service. **Decision:** dedupe in the service; the unique constraint covers the fully-specified case only. Documented.)

2. **`ListingSnapshot`** (`listing_snapshots`) — immutable point-in-time listing observation, mirroring `PriceSnapshot` / `GradedPriceSnapshot`.
   - `id`, `card_id` (FK, index), `variant` (index), `source` (index, e.g. `"ebay"`), `listing_id` (str, the provider's stable id)
   - `title: str | None`, `price: float | None`, `currency: str | None`
   - `listing_type: str | None` (`"fixed_price" | "auction"`)
   - `auction_end_at: datetime | None` (UtcDateTime; null for fixed-price)
   - `url: str | None`, `condition: str | None`, `quantity: int | None`
   - `source_updated_at: str` (empty-string sentinel, default `""` — same reason as `PriceSnapshot`)
   - `fetched_at: datetime` (UtcDateTime, default `_utcnow`)
   - Unique `uq_listing` on `(card_id, variant, source, listing_id, source_updated_at)`; index `ix_listing_lookup` on `(card_id, variant, source, fetched_at)`.

3. **`AlertEvent`** (`alert_events`) — the notification log; the in-app center reads from this.
   - `id`, `watch_id: int | None` (FK watchlist.id, nullable — an alert could be system-generated; index)
   - `card_id: str | None` (FK, index; denormalized for fast listing without a join)
   - `alert_type: str` (index), `message: str` (human-readable, the feed copy)
   - `context: str | None` (JSON: price, listing url, auction_end_at, drop_at, etc. — structured payload for the UI + deep-link)
   - `delivered_inapp: bool` (default true — the row existing *is* the in-app delivery)
   - `delivered_push: bool` (default false), `delivered_email: bool` (default false)
   - `read_at: datetime | None` (UtcDateTime, nullable — null = unread; the badge counts `read_at IS NULL`)
   - `created_at: datetime` (UtcDateTime, default `_utcnow`)
   - Index `ix_alert_unread` on `(read_at, created_at)`.

4. **`PushSubscription`** (`push_subscriptions`) — one per browser/device that opted into push.
   - `id`, `endpoint: str` (unique — one subscription per endpoint), `p256dh: str`, `auth: str`, `created_at` (UtcDateTime).

No new files under `data/` except DB rows. No `data/` contents deleted.

### New provider: `ListingsProvider` (mirrors `GradedPriceProvider` / `PriceProvider`)

- `prices/listings_provider.py`:
  - `ListingQuote` frozen dataclass: `card_id, variant, listing_id, title, price, currency, listing_type, auction_end_at, url, condition, source, source_updated_at` — `source` is **required (no default)**, matching the post-fix `GradedPriceQuote`.
  - `ListingsProvider` Protocol: `name: str`, `fetch_listings(card_id, variant) -> list[ListingQuote]`; returns `[]` on no-key / transport error / id mismatch / parse failure; **never raises**.
- `prices/ebay_listings.py`: `EbayListingsProvider` (httpx + tenacity).
  - Env `CARDPLATFORM_LISTINGS_API_KEY` + `CARDPLATFORM_LISTINGS_BASE_URL` (default eBay Browse API base).
  - Maps `card_id` → search query from the catalog (set name + number + card name; the catalog lookup uses the existing `Card` / `CardSet` tables), fetches active listings, returns `ListingQuote`s. Fixed-price and auction both returned (auction carries `auction_end_at`).
  - Error model **identical to `PkmnPricesProvider`**: no key → `[]` without touching the network; tenacity retry on transport / 5xx / 429 (terminal); bad-JSON raises `_TerminalHttpError` (terminal, one attempt — do not retry on a 200-with-garbage body); 404/401 terminal. **Never raises out of `fetch_listings`.**
  - **Documented follow-ups** (not blocking): eBay search is keyword-based, so exact-card match may include noise — we surface `source` + `url` on every quote so the user can verify, and we never assert a listing is "the" card; a tighter id-mapping (e.g. by UPC/ISBN where present) is a later refinement. TCGplayer is the TCG-native source but has no freely-public listings API — it's a **future swappable adapter**, not this phase.

### New service: `ListingsService` (mirrors `GradedPriceService`)

- `prices/listings_service.py`:
  - `refresh_listings(card_id, variant)` — fetch via provider, dedupe against existing snapshots via `_already_recorded` (same shape as `GradedPriceService._already_recorded_graded`), insert immutable `ListingSnapshot` rows, return count. Raises `RuntimeError` only when no provider is configured (matching graded). Returns `0` on provider `[]`.
  - `latest_listings(card_id, variant)` → list of the newest snapshot's quotes (newest `fetched_at`, then `id` desc) — the card-detail "active listings" list.
  - `has_stock(card_id, variant)` → `bool` (any quote in the latest snapshot). `lowest_price(card_id, variant)` → `float | None` (min price; `None` if no listings — honest, never `0.0`).
  - `previous_listing_ids(card_id, variant)` → set of `listing_id`s from the snapshot before the latest — the diff cursor for `restock` / `new_listing`.

### New service: `AlertEngine` (`alerts/engine.py`)

`check_alerts()` — the poll tick. For each active `Watch`, refresh listings (for the listing-based types) then evaluate. **Idempotency rules (the meat of this service):**

- **restock:** `previous = previous_listing_ids`, `current = latest listing_ids`. Fire iff `previous` was empty (or absent) **and** `current` is non-empty. Update `last_seen_listing_ids = current` after evaluating. Message: "Restocked — N listings on eBay" with the lowest price.
- **new_listing:** fire for each `listing_id` in `current` not in `previous` (batch into one `AlertEvent` with the count + the new ids' urls in `context`). Never fires if `previous` is absent (first poll establishes the baseline — no alert, honest "we just started watching"). Update `last_seen_listing_ids = current`.
- **price_target:** `low = lowest_price`. Fire iff `low is not None` **and** `low <= target_price` **and** the watch is not already in "fired-below" state (track via `last_fired_at` + a per-watch cooldown `alert_cooldown_min` — re-fire only after the price has risen back above target, i.e. `last_fired_at` is reset when `low > target`). Never fires `0.0`.
- **auction_ending:** for each auction in the latest snapshot with `auction_end_at` in `[now, now + auction_window_min]` and whose `listing_id` has not already fired (track fired auction ids in `context`/a side set keyed by `(watch_id, listing_id)`), fire "Auction ending in Nm — <title>". One event per auction.
- **drop_time:** `drop_at` known. Fire iff `now >= (drop_at - lead_time_min)` **and** `last_fired_at` is null (first fire). Message: "Vending drop at <time> — <label>" (and a second fire at `drop_at` if a lead-time was used). This is pure datetime math — **no provider, no network** — so it works even when no listings key is set.

On a fire: build the human `message` + `context` JSON, create an `AlertEvent` (`delivered_inapp=True`), update `Watch.last_fired_at` / `last_seen_listing_ids`, then hand the event to `NotificationService.dispatch`.

**Never raises** out of `check_alerts` — a provider `[]` or a missing config degrades to "no data this tick", not an error. Honest empty states throughout: no listings → no restock/new-listing/price-target/auction event fires (and the card-detail listing list shows "no active listings — set a listings source key" when no provider configured).

### New service: `NotificationService` (`alerts/notify.py`)

`dispatch(alert_event)` — fans the one event out to configured channels:
- **in-app:** always (the `AlertEvent` row *is* the in-app record; `delivered_inapp=True` on creation).
- **web push:** iff VAPID configured (`settings.vapid_public_key` + `vapid_private_key` present) **and** ≥1 `PushSubscription` exists. Use a web-push library to send to every subscription; set `delivered_push=True` on success (best-effort: a failed push to one endpoint doesn't fail the event; prune 410/404 endpoints). Without VAPID → skip (honest, no fake send).
- **email:** iff SMTP configured (`settings.smtp_host` present). Send via `smtplib` (sync, in a thread so the poll tick isn't blocked); set `delivered_email=True` on success. Without SMTP → skip.

A `cardplatform gen-vapid` CLI helper generates a VAPID keypair and prints env lines (so setup is one command, like `refresh-graded-prices`).

### Polling

- `cardplatform check-alerts` CLI command — runs one `check_alerts()` tick. For local-first use, the user points an OS scheduler (cron / Task Scheduler) at it. Honest framing: **alerts only fire while a `check-alerts` run happens** (and push only while the backend is reachable for subscribe). Documented.
- An optional in-process asyncio loop in the API server (`CARDPLATFORM_ALERT_POLL_MIN`, default 15) runs `check_alerts()` every tick while the dev server is up, so it "just works" during development without cron.

### Config (`config.py`, env-prefixed `CARDPLATFORM_`)

- `listings_api_key: str | None = None`, `listings_base_url: str = "https://api.ebay.com/buy/browse/v1"` (default; the adapter is swappable).
- `vapid_public_key: str | None`, `vapid_private_key: str | None`, `vapid_subject: str | None` (a `mailto:` or URL).
- `smtp_host: str | None`, `smtp_port: int = 587`, `smtp_user: str | None`, `smtp_password: str | None`, `smtp_from: str | None`.
- `alert_poll_min: int = 15`, `alert_cooldown_min: int = 60` (price-target re-fire floor).

### New API endpoints (`api.py`, all additive; `func.lower(...).like` for any text search)

- `GET /watchlist` — list watches (optional `?card_id=`, `?active=`).
- `POST /watchlist` — create (validate `alert_type`; require `target_price` for `price_target`, `drop_at` for `drop_time`; 404 via `_require_card` when `card_id` given).
- `PATCH /watchlist/{id}` — pause/resume / edit thresholds.
- `DELETE /watchlist/{id}`.
- `GET /alerts` — list `AlertEvent`s, newest first; `?unread=true`; paginated.
- `PATCH /alerts/{id}` — mark read (`read_at = now`). `POST /alerts/read-all`.
- `GET /alerts/unread-count` → `{count}` (the badge).
- `POST /cards/{id}/listings?variant=` — refresh + return latest listings (the card-detail "active listings" list; degrades to `[]` + a `listings_unavailable` flag when no provider).
- `POST /push/subscribe` (body: `{endpoint, p256dh, auth}`) — upsert by `endpoint`. `DELETE /push/subscribe` (by endpoint).
- Existing `GET /cards/{id}/grading-upside` reused unchanged on the card-detail screen.

### Frontend (Vite + React 19 PWA, Grading Lab dark theme)

The current 2-view app (`App.tsx`: Scan/Portfolio, bottom nav in standalone) expands to a 5-tab shell:

- **Scan** (existing camera flow, polished) — the onboarding magic moment; first run lands here, no sign-up.
- **Vault** (existing `PortfolioView`, polished) — total value, holdings, trends; tap → Card detail.
- **Alerts** (new, **default home**) — the feed: `AlertEvent`s grouped by type, filter chips (All / Restock / Price / Auction / Drops), unread badge, pull-to-refresh; empty state sells the capability ("Your personal card-market radar — watch a card to get pinged the moment it restocks, hits your price, or a vending machine drops."). Each row deep-links to Card detail or the listing URL. "Watch a card" CTA.
- **Browse** (new) — debounced search of the catalog (`func.lower(name).like` via a search endpoint), results → Card detail.
- **More** (settings) — channel status with honest nudges ("Enable push", "Set email", "Listings source: eBay — set key"), poll interval, about. Push subscription is requested here (and on first "Watch" if enabled).
- **Card detail screen** (new, shared target of Scan/Browse/Vault/Alerts) — card art, market price + staleness, the existing `GradingUpside` panel, the existing `PriceChart`, a new **active listings** list (from `/cards/{id}/listings`), and a **"Watch this card"** sheet (choose alert type → `POST /watchlist`; for `drop_time`, a datetime + lead-time picker; for `price_target`, a target field; for `auction_ending`, a window field).
- **Onboarding:** first run → Scan (camera-first). After a successful scan with a market price, a contextual "Watch this card" prompt appears (Collectr-style: account/setup deferred, magic moment first).

Mobile-safe throughout: 44px touch targets, safe-area insets, stacked-on-mobile layouts. Existing 65 vitest tests stay green; new tests added.

### Testing (TDD, mirrors the 3b discipline)

Backend pytest (extend beyond 374):
- `test_ebay_listings_provider.py` — mocked httpx: degrades to `[]` w/o key, parses fixed-price + auction, `auction_end_at` parse, bad-JSON terminal (no retry), 5xx/429 retry, 404/401 terminal, never raises.
- `test_listings_service.py` — refresh dedupe + immutable inserts, `latest_listings` newest-first, `has_stock` / `lowest_price` (None when empty, never 0.0), `previous_listing_ids`.
- `test_alert_engine.py` — each of the 5 alert types fires correctly; **idempotency**: restock fires only on empty→stocked; new_listing skips first poll (baseline); price_target cooldown + reset-above-target; auction one-event-per-auction; drop_time fires at lead/at drop, not before. Provider `[]` → no event, no raise.
- `test_notification_service.py` — in-app always; push only with VAPID + subscription (best-effort, prunes 410); email only with SMTP; all skip honestly when unconfigured.
- `test_watchlist_api.py`, `test_alerts_api.py`, `test_push_api.py`, `test_listings_api.py` — CRUD + 404s + unread-count + read-all + push upsert/dedupe.
- `test_migrations_alerts.py` — new tables created, existing rows/101 scans untouched, nullable columns added on the existing DB.

Frontend vitest (extend beyond 65):
- `AlertsFeed.test.tsx` — renders events grouped by type; unread badge count; filter chips; honest empty state copy; deep-link.
- `WatchCardSheet.test.tsx` — alert-type picker shows the right fields (target for price_target, datetime for drop_time, window for auction_ending); POSTs correct JSON; `drop_time` works without a listings key.
- `CardDetail.test.tsx` — price + staleness, grading upside panel, active listings (empty → "set a listings key", never fake), watch CTA.
- `Browse.test.tsx` — debounced search, results → detail.
- Honest-empty-state assertions throughout (no `$0`, no fabricated listing, degrade messages).

### Sacred constraints (preserved, verbatim)

- **No ad-hoc price resolution** — only `PriceService.latest_price` / `GradedPriceService.latest_graded` / `ListingsService.latest_listings` / `lowest_price`.
- **Snapshots immutable** — `ListingSnapshot` rows are never updated, exactly like `PriceSnapshot`.
- **`func.lower(col).like`** for every text search (catalog search, watchlist filters, alert listing lookups).
- **Honest empty states** — no fake restock/listing/alert, no `$0`, degrade messages ("listings source unavailable — set `CARDPLATFORM_LISTINGS_API_KEY`", "enable push", "set email"). Em dash for missing.
- **Providers never raise** — `EbayListingsProvider.fetch_listings` returns `[]` on any failure; `AlertEngine.check_alerts` never raises.
- **Staleness surfaced** — listing `fetched_at` and price `source_updated_at` shown on the card detail.
- **`data/` untouched** — only new DB tables; no existing file/image deleted (20,391 images, FAISS index, 105 scans all preserved).
- **Python 3.12 only** via `backend/.venv`.

## Out of scope (honest)

- Deal-sniper math (rip-vs-flip, sealed EV, listings-vs-sold-comps analysis) — Phase 05's deeper leg, still planned.
- Set-completion optimizer (missing-cards grid, cheapest path) — Phase 06, still planned.
- TCGplayer listings adapter (no free public API) — future swappable adapter; eBay is the v1 source.
- A curated Pokémon Center drop calendar (auto-ingested scheduled drops) — v1 `drop_time` watches are user-entered; an auto-curated feed is a follow-up.
- On-device inference for the scanner (Phase 08) — unrelated.

## Task shape (for the implementation plan)

~9 tasks, dependency-ordered with parallelism where independent (T3 ‖ T4 after T2; T6 ‖ T7 partly after T5):

- **T1** Migrations + schema (`Watch`, `ListingSnapshot`, `AlertEvent`, `PushSubscription`; no existing-table change beyond what 3b did).
- **T2** `ListingsProvider` + `EbayListingsProvider` + `ListingsService` + config (mirrors graded price).
- **T3** `AlertEngine` (5 types + idempotency + cooldown) + tests.
- **T4** `NotificationService` (in-app + push + email) + `gen-vapid` CLI + `PushSubscription` storage + tests. (parallel with T3 after T2)
- **T5** Watchlist + Alerts + Listings + Push API endpoints + `check-alerts` CLI + in-process poll loop.
- **T6** Frontend app shell (5-tab nav, routing) + Vault/Browse polish + Card detail screen.
- **T7** Frontend Alerts feed + Watch-card sheet + onboarding magic moment + More/settings (channel status, honest nudges). (partly parallel with T6)
- **T8** Site update: roadmap row (Phase 05 watchlist/notifications leg, "in progress") + scroll-animated Alerts section on the marketing site; `AI_CONTEXT.md` + `PROJECT.md`.
- **T9** Integrate, verify (pytest → N all green; vitest → N; frontend + site builds), merge → main, push, **confirm GitHub Pages deploy succeeds** (the `.nojekyll` fix is now in place — verify the new `docs/` builds and serves).

## Verification (end-to-end)

- **Backend:** `backend/.venv/Scripts/python -m pytest` all green; migrations run cleanly against the existing DB with 101 scans + catalog untouched (`SELECT count(*) FROM scan_logs` unchanged). Manual: `cardplatform check-alerts` with a listings key → `AlertEvent` rows for a watched card that restocked; without a key → listing-based alerts simply don't fire (no crash), `drop_time` alerts still fire (pure datetime).
- **Frontend:** vitest green (existing 65 + new); `npm run build` clean. Smoke (backend :8000, frontend :5173): scan → see card detail with active listings + "Watch this card"; watch a card for restock; trigger `check-alerts` → alert appears in feed + badge; enable push → subscription stored; configure SMTP → email sends; unconfigured channels show honest nudge, never a fake send.
- **Site:** `npm --prefix site run build` → `docs/`; `.nojekyll` present; Grading + new Alerts section render; `docs/superpowers/` intact; push → Pages build **succeeds** (verify via `gh api …/pages/builds`).