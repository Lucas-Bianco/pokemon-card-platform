# Phase 3c — Alerts (Watchlist + Notifications) + CollectorVault UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a CCN-style watchlist + restock/price/drop/auction notification system (in-app + web push + email) as the app's new Alerts-first home surface, plus a CollectorVault-style 5-tab UI/nav polish and a shared Card detail screen.

**Architecture:** New swappable `ListingsProvider` (eBay adapter, degrades to `[]`, never raises — mirrors `PkmnPricesProvider`) + immutable `ListingSnapshot` table feed an `AlertEngine` that diffs snapshots per active `Watch` and fires `AlertEvent`s through a `NotificationService` (in-app always; push when VAPID configured; email when SMTP configured). Frontend expands from 2 views to a 5-tab shell. All additive; sacred constraints (immutable snapshots, no ad-hoc pricing, `func.lower().like`, honest empty states, providers never raise, `data/` untouched) preserved.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite, httpx + tenacity, pytest (backend); React 19 + TypeScript + Vite PWA, vitest (frontend); Next.js 15 static export (site). Web push via `pywebpush`. Email via `smtplib`.

**Spec:** `docs/superpowers/specs/2026-08-02-alerts-watchlist-design.md` (read it first — it is the contract).

---

## File structure map

**Backend (new):**
- `db/models.py` — add `Watch`, `ListingSnapshot`, `AlertEvent`, `PushSubscription` models.
- `prices/listings_provider.py` — `ListingQuote` dataclass + `ListingsProvider` Protocol.
- `prices/ebay_listings.py` — `EbayListingsProvider` (mirrors `pkmnprices.py`).
- `prices/listings_service.py` — `ListingsService` (mirrors `graded_service.py`).
- `alerts/engine.py` — `AlertEngine.check_alerts()` (5 alert types + idempotency).
- `alerts/notify.py` — `NotificationService.dispatch()` (in-app + push + email).
- `alerts/api_models.py` — Pydantic out models for watchlist/alerts/listings/push.
- `config.py` — listings/vapid/smtp/alert settings.
- `cli.py` — `check-alerts`, `gen-vapid` commands.
- `api.py` — watchlist/alerts/listings/push endpoints + in-process poll loop.

**Backend (new tests):**
- `tests/test_listings_provider.py`, `tests/test_listings_service.py`, `tests/test_alert_engine.py`, `tests/test_notification_service.py`, `tests/test_watchlist_api.py`, `tests/test_alerts_api.py`, `tests/test_listings_api.py`, `tests/test_push_api.py`, `tests/test_migrations_alerts.py`.

**Frontend (new):**
- `src/components/AppShell.tsx` — 5-tab nav + routing (replaces the inline nav in `App.tsx`).
- `src/components/AlertsFeed.tsx` — the home feed.
- `src/components/WatchCardSheet.tsx` — "Watch this card" alert-type picker.
- `src/components/CardDetail.tsx` — shared card screen (price, grading upside, chart, listings, watch CTA).
- `src/components/Browse.tsx` — catalog search.
- `src/components/More.tsx` — settings / channel status.
- `src/api/client.ts` + `types.ts` — watchlist/alerts/listings/push client + types.
- `src/App.tsx` — rewired to `AppShell`.
- `src/styles.css` — new component styles (mobile-safe, Grading Lab theme).

**Frontend (new tests):** `__tests__/AlertsFeed.test.tsx`, `WatchCardSheet.test.tsx`, `CardDetail.test.tsx`, `Browse.test.tsx`.

**Site:** `site/app/sections/data.ts` (roadmap), `site/app/sections/Alerts.tsx` (new scroll-animated section), `site/app/page.tsx`, rebuild → `docs/`.

**Docs:** `AI_CONTEXT.md`, `PROJECT.md`.

---

## Task 1: Migrations + schema (Watch, ListingSnapshot, AlertEvent, PushSubscription)

**Files:**
- Modify: `backend/src/cardplatform/db/models.py` (append 4 models)
- Verify: `backend/src/cardplatform/cli.py` and `api.py` call `run_migrations(engine)` after `create_all()` (already wired in 3b — confirm, don't change)
- Test: `backend/tests/test_migrations_alerts.py`

**Contracts (verbatim — subagents must match field names exactly):**

```python
class Watch(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("card_id", "variant", "alert_type", "target_price", "drop_at",
                         name="uq_watch"),
        Index("ix_watch_card", "card_id", "variant"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id"), index=True, default=None)
    subject_label: Mapped[str | None] = mapped_column(String, default=None)
    variant: Mapped[str | None] = mapped_column(String, default=None)
    alert_type: Mapped[str] = mapped_column(String, index=True)
    target_price: Mapped[float | None] = mapped_column(Float, default=None)
    drop_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    lead_time_min: Mapped[int | None] = mapped_column(Integer, default=None)
    auction_window_min: Mapped[int | None] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_listing_ids: Mapped[str | None] = mapped_column(String, default=None)  # JSON list
    last_fired_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

```python
class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"
    __table_args__ = (
        UniqueConstraint("card_id", "variant", "source", "listing_id", "source_updated_at",
                         name="uq_listing"),
        Index("ix_listing_lookup", "card_id", "variant", "source", "fetched_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    variant: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    listing_id: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, default=None)
    price: Mapped[float | None] = mapped_column(Float, default=None)
    currency: Mapped[str | None] = mapped_column(String, default=None)
    listing_type: Mapped[str | None] = mapped_column(String, default=None)
    auction_end_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    url: Mapped[str | None] = mapped_column(String, default=None)
    condition: Mapped[str | None] = mapped_column(String, default=None)
    quantity: Mapped[int | None] = mapped_column(Integer, default=None)
    source_updated_at: Mapped[str] = mapped_column(String, default="", server_default="")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

```python
class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_unread", "read_at", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist.id"), index=True, default=None)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id"), index=True, default=None)
    alert_type: Mapped[str] = mapped_column(String, index=True)
    message: Mapped[str] = mapped_column(String)
    context: Mapped[str | None] = mapped_column(String, default=None)  # JSON
    delivered_inapp: Mapped[bool] = mapped_column(Boolean, default=True)
    delivered_push: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_email: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

```python
class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
```

**Note:** These are all NEW tables → created by `Base.metadata.create_all()`. `run_migrations`' `_ADDITIVE_COLUMNS` adds nothing this task (no new columns on existing tables). Do NOT add the new tables to `_ADDITIVE_COLUMNS` (it is ALTER-only; new tables belong to `create_all`).

- [ ] Step 1: Add the four models to `db/models.py` (verbatim above; reuse existing imports — `JSON` not needed; `UniqueConstraint`, `Index`, `Integer`, `String`, `Float`, `Boolean`, `ForeignKey`, `UtcDateTime`, `_utcnow` already imported).
- [ ] Step 2: Write `tests/test_migrations_alerts.py`:
  - `test_new_tables_created` — after `create_all` + `run_migrations` on a fresh temp DB, `inspect(engine).get_table_names()` contains `watchlist`, `listing_snapshots`, `alert_events`, `push_subscriptions`.
  - `test_existing_data_preserved` — copy the real `data/cardplatform.sqlite3` to tmp, run `create_all` + `run_migrations`, assert `SELECT count(*) FROM scan_logs` unchanged (105) and `SELECT count(*) FROM cards` unchanged; assert the 4 new tables exist and are empty.
  - `test_models_roundtrip` — insert one row into each new table (with aware datetimes via `UtcDateTime`) and read back; assert `Watch.active` defaults True, `AlertEvent.delivered_inapp` defaults True, `PushSubscription.endpoint` unique raises on duplicate.
- [ ] Step 3: Run `backend/.venv/Scripts/python -m pytest tests/test_migrations_alerts.py -v` → all pass.
- [ ] Step 4: Run full suite `backend/.venv/Scripts/python -m pytest -q` → all green (374 unchanged + new).
- [ ] Step 5: Commit: `git add -A && git commit -m "feat(alerts): Watch/ListingSnapshot/AlertEvent/PushSubscription schema (T1)"`.

---

## Task 2: ListingsProvider + EbayListingsProvider + ListingsService

**Files:**
- Create: `backend/src/cardplatform/prices/listings_provider.py`
- Create: `backend/src/cardplatform/prices/ebay_listings.py`
- Create: `backend/src/cardplatform/prices/listings_service.py`
- Modify: `backend/src/cardplatform/config.py` (add listings settings)
- Test: `backend/tests/test_listings_provider.py`, `backend/tests/test_listings_service.py`

**Contracts (verbatim):**

`listings_provider.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

@dataclass(frozen=True)
class ListingQuote:
    card_id: str
    variant: str
    listing_id: str
    title: str | None
    price: float | None
    currency: str | None
    listing_type: str | None       # "fixed_price" | "auction"
    auction_end_at: datetime | None
    url: str | None
    condition: str | None
    source: str                     # REQUIRED, no default (matches GradedPriceQuote)
    source_updated_at: str | None

class ListingsProvider(Protocol):
    name: str
    def fetch_listings(self, card_id: str, variant: str) -> list[ListingQuote]: ...
```

`ebay_listings.py` — `EbayListingsProvider` mirrors `PkmnPricesProvider` line-for-line in error/retry discipline:
- `name = "ebay"`. `__init__(self, settings=None)`.
- `fetch_listings(card_id, variant)` → `[]` without key (no network); else `_search` then `_parse`.
- Search query: look up the `Card` + `CardSet` from the DB (inject a small `catalog_lookup(card_id) -> (set_name, number, card_name)` callable, or accept a `session`/`catalog` dependency). Build query `f"{card_name} {set_name} {number}"`. Hit `{base}/item_summary/search?q=...&filter=conditions:{...}` (eBay Browse API). Document keyword-noise follow-up in the module docstring (mirror PkmnPrices' id-mapping caveat): eBay search is keyword-based; we surface `source` + `url` on every quote so the user verifies; tighter id-mapping is a later refinement.
- `_TerminalHttpError` for 404/401/bad-JSON (terminal, one attempt); retry on transport/5xx/429; `RetryError` → `[]`; parse failures (TypeError/ValueError/KeyError) → `[]` with a warning. **NEVER raises** out of `fetch_listings`.
- `_parse` maps eBay `itemSummaries` → `ListingQuote`s: `listing_id=item_id`, `price`/`currency` from `price.value`/`price.currency`, `url=item_web_url`, `title=title`, `listing_type="auction"` if `item_summary.additionalImages`/`bid` present else `"fixed_price"` (use eBay's `buyingOptions`: contains `"BIDDING"` → auction, `"FIXED_PRICE"`/`BUY_IT_NOW"` → fixed_price), `auction_end_at` from `item_end_date`/`item_end_date` (parse ISO, tz-aware UTC) or None, `condition` from `condition` field. Skip rows missing `listing_id` or unparseable price. `source="ebay"`, `source_updated_at` from `last_sold_date`? no — use eBay's response or None.

`config.py` additions:
```python
listings_api_key: str | None = Field(default=None)
listings_base_url: str = Field(default="https://api.ebay.com/buy/browse/v1")
```

`listings_service.py` — `ListingsService` mirrors `GradedPriceService`:
- `__init__(self, session, provider=None)`.
- `refresh_listings(card_id, variant) -> int`: raises `RuntimeError` if no provider; else for each `ListingQuote`, dedupe via `_already_recorded(card_id, variant, source, listing_id, stamp)`, insert immutable `ListingSnapshot`, commit, return count. `0` on provider `[]`.
- `latest_listings(card_id, variant) -> list[ListingSnapshot]`: newest `fetched_at` (then `id` desc) snapshot's rows. Implementation: subquery max `fetched_at` per `(card_id, variant, source)` then select rows with that stamp, ordered by `price` asc (lowest first for the UI). Return `[]` if none.
- `has_stock(card_id, variant) -> bool`: `latest_listings` non-empty.
- `lowest_price(card_id, variant) -> float | None`: min `price` over latest listings where price not None; `None` if none (never `0.0`).
- `previous_listing_ids(card_id, variant) -> set[str]`: the `listing_id`s from the snapshot strictly older than the latest (the second-newest `fetched_at`). `set()` if no prior snapshot.
- `_already_recorded(card_id, variant, source, listing_id, source_updated_at) -> bool` (mirrors `_already_recorded_graded`; uses `""` sentinel for `source_updated_at`).

- [ ] Step 1: Write `tests/test_listings_provider.py` (mock `httpx.get` via monkeypatch, mirroring `test_pkmnprices_provider.py`):
  - `test_no_key_returns_empty_no_network` — no key → `[]`, assert `httpx.get` not called.
  - `test_parses_fixed_price_and_auction` — 200 with two itemSummaries (one FIXED_PRICE, one BIDDING with `item_end_date`) → 2 quotes, auction one has `listing_type=="auction"` and aware `auction_end_at`.
  - `test_bad_json_terminal_no_retry` — 200 with garbage body → `[]`, assert `httpx.get` called once (not retried). (Assert `http_max_attempts` not consumed.)
  - `test_404_terminal` → `[]`, one attempt.
  - `test_5xx_retries_then_empty` → `[]`.
  - `test_parse_failure_returns_empty` — 200 with unexpected shape → `[]`, no raise.
  - `test_never_raises` — patch `httpx.get` to raise `httpx.HTTPError` → `[]`, no raise.
- [ ] Step 2: Implement `listings_provider.py`, `ebay_listings.py`, config additions.
- [ ] Step 3: Write `tests/test_listings_service.py`:
  - `test_refresh_dedupes_and_is_immutable` — two refreshes with identical quotes → 1 snapshot row; second refresh returns 0.
  - `test_latest_listings_newest_first_lowest_price_first` — insert two snapshots (old high price, new low price) → `latest_listings` returns the new one's rows ordered price asc.
  - `test_has_stock_and_lowest_price` — empty → `has_stock=False`, `lowest_price=None` (NOT 0.0).
  - `test_previous_listing_ids` — old snapshot ids `{A,B}`, new `{B,C}` → `previous_listing_ids == {A,B}` (the prior snapshot).
  - `test_refresh_no_provider_raises` — `ListingsService(session)` (no provider) `.refresh_listings` → `RuntimeError`.
  - `test_refresh_no_key_returns_zero` — provider with no key → `refresh_listings` returns 0, no raise.
- [ ] Step 4: Implement `listings_service.py`.
- [ ] Step 5: Run both test files + full suite → green.
- [ ] Step 6: Commit: `feat(alerts): ListingsProvider + EbayListingsProvider + ListingsService (T2)`.

---

## Task 3: AlertEngine (5 alert types + idempotency + cooldown)

**Files:**
- Create: `backend/src/cardplatform/alerts/engine.py`
- Test: `backend/tests/test_alert_engine.py`

**Contract:** `AlertEngine(session, listings_service=None, notifier=None)`. `check_alerts() -> int` (count of events fired). Iterates `select(Watch).where(Watch.active == True)`. For listing-based types (`restock`, `new_listing`, `price_target`, `auction_ending`) refresh listings first if `listings_service` present (skip silently if `None` or provider returns 0/`[]` — no event, no raise). `drop_time` needs no listings.

**Idempotency rules (verbatim from spec — subagents must implement exactly):**

```python
# restock: fire iff previous was empty/absent AND current non-empty.
prev = listings_service.previous_listing_ids(card_id, variant) if listings_service else set()
curr = {s.listing_id for s in listings_service.latest_listings(card_id, variant)} if listings_service else set()
fired_restock = (not prev) and bool(curr)
# new_listing: fire ids in curr not in prev; skip entirely if prev is empty AND this is the first poll
#   (no prior snapshot) — first poll establishes baseline, no alert.
new_ids = curr - prev
fired_new_listing = bool(new_ids) and has_prior_snapshot
# price_target: lowest <= target AND not already fired-below (track via last_fired_at; reset when low > target).
low = listings_service.lowest_price(card_id, variant)
# fire iff low is not None and low <= target and (last_fired_at is None or cooldown elapsed and price re-crossed)
# Simplify: maintain a "fired_below" boolean inferred from last_fired_at within cooldown window; re-arm when low > target.
# price_target fires once per downward crossing; cooldown alert_cooldown_min prevents spam if price hovers at target.
# auction_ending: for each auction in latest with auction_end_at in [now, now+window] not already fired for (watch, listing_id): one event.
# drop_time: fire iff now >= drop_at - lead_time_min and last_fired_at is None. (lead_time_min default 0.)
```

`has_prior_snapshot` = `listings_service.previous_listing_ids(...)` is non-empty OR a prior snapshot exists even if empty — implement as `bool(session.query(ListingSnapshot).filter_by(card_id, variant).count() > 0 and previous fetched_at exists)`. Concretely: `has_prior = latest_listings fetched_at is not None AND there exists a snapshot with fetched_at < latest_fetched_at`. If `curr` non-empty but no prior snapshot at all → first poll, `new_listing` does NOT fire (baseline), but `restock` ALSO does not fire (we don't know it was empty before). Actually restock fires on `not prev and curr` — on first poll `prev=set()` (no prior) → restock would fire, which is wrong (we don't know prior state). **Fix:** restock fires iff a prior snapshot exists AND prior listing_ids empty AND curr non-empty. So both restock and new_listing require a prior snapshot. Use `has_prior_snapshot` to gate both. Update the spec mentally: first poll establishes baseline; no restock/new_listing alert until the second poll.

On fire: build `message` + `context` JSON, `session.add(AlertEvent(watch_id=..., card_id=..., alert_type=..., message=..., context=json.dumps(...), delivered_inapp=True))`, update `Watch.last_fired_at = now` and `Watch.last_seen_listing_ids = json.dumps(sorted(curr))`, then `notifier.dispatch(event)` if notifier. Commit once at end of `check_alerts`. Return count.

`check_alerts()` **never raises** — wrap each watch's evaluation in try/except logging a warning and continuing (one bad watch doesn't abort the tick).

- [ ] Step 1: Write `tests/test_alert_engine.py` (use an in-memory or temp SQLite session + a fake `ListingsService`/fake provider so no network):
  - `test_restock_fires_on_empty_to_stocked` — prior snapshot empty listings, new snapshot has 1 listing, watch restock → 1 event "Restocked".
  - `test_restock_no_fire_first_poll` — no prior snapshot, new has listings → 0 events (baseline).
  - `test_restock_no_fire_when_already_stocked` — prior {A}, curr {A,B} (both non-empty) → 0 restock events.
  - `test_new_listing_fires_new_ids` — prior {A}, curr {A,B} → 1 event with context listing the new id B.
  - `test_new_listing_no_fire_first_poll` — no prior, curr {A,B} → 0 events.
  - `test_price_target_fires_below_target_then_rearms` — target 40, prior low 50, curr low 38 → fires; next tick low 38 (still below, cooldown) → no fire; tick low 45 (above) re-arms; tick low 38 → fires again.
  - `test_price_target_never_zero` — low 0.0 treated as… (lowest_price returns None for empty; if a listing literally prices 0, that's an edge — assert price 0 <= target fires but document; keep honest: a $0 listing is suspicious data, but we don't fabricate — if provider returns 0 we surface it. Test: target 40, curr low 0.0 → fires "Price ≤ $40" with context price 0.0. This is acceptable: the listing exists.)
  - `test_auction_ending_one_event_per_auction` — two auctions ending in 20min (window 30) → 2 events; next tick same auctions → 0 (already fired, tracked by listing_id).
  - `test_drop_time_fires_at_lead_and_drop` — drop_at in 1h, lead_time_min 60 → fires now (now >= drop_at-60min); then at drop_at fires again (second fire). Use monkeypatched `datetime.now` or inject a clock callable `now()` (don't use `datetime.now` directly — inject `_clock` default `lambda: datetime.now(timezone.utc)` for testability).
  - `test_drop_time_no_fire_before_lead` — drop_at in 2h, lead 60min → 0 events.
  - `test_provider_empty_no_event_no_raise` — listings_service returns [] → 0 events, no raise.
  - `test_check_alerts_never_raises` — one watch raises internally (patch eval) → engine logs, continues, other watches still evaluated, returns count of good ones.
  - `test_inactive_watches_skipped` — active=False watch → not evaluated.
  - Idempotency across ticks: run `check_alerts` twice with no change → second returns 0 (no duplicate events).
- [ ] Step 2: Implement `alerts/engine.py` with the injectable `_clock` and the rules above. Use `json` for `last_seen_listing_ids` and `context`.
- [ ] Step 3: Run tests + full suite → green.
- [ ] Step 4: Commit: `feat(alerts): AlertEngine 5 alert types + idempotency (T3)`.

---

## Task 4: NotificationService (in-app + push + email) + gen-vapid + PushSubscription storage

**Files:**
- Create: `backend/src/cardplatform/alerts/notify.py`
- Modify: `backend/src/cardplatform/config.py` (vapid + smtp + alert settings)
- Modify: `backend/src/cardplatform/cli.py` (`gen-vapid` command)
- Test: `backend/tests/test_notification_service.py`

**Contract:**
```python
class NotificationService:
    def __init__(self, session, settings=None): ...
    def dispatch(self, event: AlertEvent) -> None:
        # in-app: already delivered (row exists); ensure delivered_inapp=True.
        # push: if vapid_public_key and vapid_private_key: for each PushSubscription:
        #   try pywebpush.WebPusher(subscription).send(payload, vapid_private_key=..., vapid_claims={"sub": vapid_subject or "mailto:..."});
        #   on 410/404 delete the subscription (prune); on other error log+continue.
        #   set event.delivered_push=True if at least one sent successfully.
        # email: if smtp_host: smtplib.SMTP(smtp_host, smtp_port) in a thread; set delivered_email=True on success; on error log+continue.
        # Never raises out of dispatch — channel failures degrade (mark delivered_* False, log).
```

`config.py` additions:
```python
vapid_public_key: str | None = Field(default=None)
vapid_private_key: str | None = Field(default=None)
vapid_subject: str | None = Field(default=None)
smtp_host: str | None = Field(default=None)
smtp_port: int = Field(default=587)
smtp_user: str | None = Field(default=None)
smtp_password: str | None = Field(default=None)
smtp_from: str | None = Field(default=None)
alert_poll_min: int = Field(default=15)
alert_cooldown_min: int = Field(default=60)
```

`cli.py` `gen-vapid`:
```python
@main.command("gen-vapid")
def gen_vapid():
    # Use pywebpush's webpush.generate_vapid_keys() (or cryptography ec.generate_private_key).
    # Print the public + private keys as CARDPLATFORM_VAPID_PUBLIC_KEY / ..._PRIVATE_KEY env lines.
    # Do NOT write to any file; just print (mirrors the "set a key" convention).
```

Add `pywebpush` to `backend/requirements`/pyproject (whichever the project uses — check `pyproject.toml`). If `pywebpush` is heavy, the minimal path: use `cryptography` (likely already present via the ML stack) to generate VAPID keys, and `httpx` to POST the Web Push protocol manually. **Decision:** add `pywebpush` (standard, handles the Web Push protocol + encryption) — confirm it's acceptable; it's a single well-maintained dep. Document in the commit.

- [ ] Step 1: Write `tests/test_notification_service.py`:
  - `test_in_app_always` — no vapid, no smtp → `delivered_inapp=True`, `delivered_push=False`, `delivered_email=False`, no raise.
  - `test_push_when_vapid_and_subscription` — settings with vapid keys, 1 PushSubscription, monkeypatch `pywebpush.WebPusher(...).send` to succeed → `delivered_push=True`.
  - `test_push_skipped_without_vapid` — no vapid keys → `delivered_push=False`, send not called.
  - `test_push_skipped_without_subscriptions` — vapid set, 0 subscriptions → `delivered_push=False`, no raise.
  - `test_push_prunes_410` — a subscription whose send raises a 410-gone → subscription deleted, event still `delivered_push=False` (or True if another succeeded), no raise.
  - `test_email_when_smtp` — smtp_host set, monkeypatch `smtplib.SMTP` → `delivered_email=True`.
  - `test_email_skipped_without_smtp` — no smtp → `delivered_email=False`, no raise.
  - `test_never_raises` — push + email both raise → dispatch returns None, no raise; event.delivered_* reflect what happened.
- [ ] Step 2: Implement `notify.py` (run email in a `concurrent.futures.ThreadPoolExecutor` so the tick isn't blocked; push is sync but fast).
- [ ] Step 3: Add `gen-vapid` CLI + config fields + `pywebpush` dependency.
- [ ] Step 4: Run tests + full suite → green.
- [ ] Step 5: Commit: `feat(alerts): NotificationService in-app+push+email + gen-vapid (T4)`.

---

## Task 5: Watchlist + Alerts + Listings + Push API + check-alerts CLI + poll loop

**Files:**
- Modify: `backend/src/cardplatform/api.py` (endpoints + in-process poll loop)
- Create: `backend/src/cardplatform/alerts/api_models.py` (Pydantic out models)
- Modify: `backend/src/cardplatform/cli.py` (`check-alerts` command)
- Test: `backend/tests/test_watchlist_api.py`, `tests/test_alerts_api.py`, `tests/test_listings_api.py`, `tests/test_push_api.py`

**Pydantic out models (`alerts/api_models.py`):**
```python
class WatchOut(BaseModel):
    id: int; card_id: str | None; subject_label: str | None; variant: str | None
    alert_type: str; target_price: float | None; drop_at: datetime | None
    lead_time_min: int | None; auction_window_min: int | None; active: bool
    last_fired_at: datetime | None; created_at: datetime
class WatchCreate(BaseModel):
    card_id: str | None = None; subject_label: str | None = None; variant: str | None = None
    alert_type: str; target_price: float | None = None; drop_at: datetime | None = None
    lead_time_min: int | None = None; auction_window_min: int | None = None
class WatchPatch(BaseModel):
    active: bool | None = None; target_price: float | None = None
    drop_at: datetime | None = None; lead_time_min: int | None = None
    auction_window_min: int | None = None
class ListingOut(BaseModel):
    listing_id: str; title: str | None; price: float | None; currency: str | None
    listing_type: str | None; auction_end_at: datetime | None; url: str | None
    condition: str | None; source: str; fetched_at: datetime
class AlertEventOut(BaseModel):
    id: int; watch_id: int | None; card_id: str | None; alert_type: str
    message: str; context: str | None; delivered_push: bool; delivered_email: bool
    read_at: datetime | None; created_at: datetime
class PushSubscribeIn(BaseModel):
    endpoint: str; p256dh: str; auth: str
```

**Endpoints (all additive; use `_require_card(card_id)` helper that already exists for 404; `func.lower(...).like` for any text search — though watchlist list filters by card_id/active only, no free text needed):**
- `GET /watchlist` → `list[WatchOut]` (optional `?card_id=` exact, `?active=true|false`).
- `POST /watchlist` → `WatchOut` 201. Validate: `alert_type` in the 5; if `alert_type=="price_target"` require `target_price is not None` (422); if `alert_type=="drop_time"` require `drop_at is not None` (422); if `card_id` given, `_require_card` (404 if unknown). Insert; return.
- `PATCH /watchlist/{id}` → `WatchOut` (404 if missing). Apply non-null patch fields.
- `DELETE /watchlist/{id}` → 204 (404 if missing).
- `GET /alerts` → `list[AlertEventOut]` newest first; `?unread=true` filters `read_at IS NULL`; limit/offset pagination (default limit 50).
- `PATCH /alerts/{id}` → mark read (`read_at = now`); 404 if missing.
- `POST /alerts/read-all` → `{"updated": N}` sets `read_at = now` where `read_at IS NULL`.
- `GET /alerts/unread-count` → `{"count": N}`.
- `POST /cards/{card_id}/listings?variant=` → refresh (`ListingsService.refresh_listings`) then return `{"listings": list[ListingOut], "listings_unavailable": bool}` where `listings_unavailable = (no provider configured)` (honest: empty list + flag, never fake). 404 if card unknown.
- `POST /push/subscribe` (body `PushSubscribeIn`) → upsert by `endpoint` (201 new / 200 existing). `DELETE /push/subscribe?endpoint=` → 204.

**In-process poll loop (api.py startup):** on app startup, if `settings.alert_poll_min > 0`, start a background `asyncio.create_task` that calls `AlertEngine(...).check_alerts()` every `alert_poll_min * 60` seconds. Guard with `settings` check; swallow exceptions per tick (log). Only runs while the server is up — honest (the CLI `check-alerts` is the durable path for cron).

**CLI `check-alerts`:** `cardplatform check-alerts` → builds a session, `AlertEngine(session, ListingsService(session, EbayListingsProvider()), NotificationService(session)).check_alerts()`, prints `N alerts fired`. Returns 0.

- [ ] Step 1: Write the 4 test files (TestClient-based, mirroring existing `test_grading_api.py` style; use the real temp-DB fixture the suite already uses):
  - watchlist: create/validate/patch/delete/404s; price_target without target → 422; drop_time without drop_at → 422; unknown card → 404.
  - alerts: list newest-first; `?unread=true`; mark read; read-all; unread-count.
  - listings: POST returns listings + `listings_unavailable=True` when no key (provider returns []); 404 unknown card.
  - push: subscribe upsert (same endpoint twice → 1 row); delete.
- [ ] Step 2: Implement `api_models.py`, endpoints, poll loop, `check-alerts` CLI.
- [ ] Step 3: Run the 4 test files + full suite → green.
- [ ] Step 4: Commit: `feat(alerts): watchlist/alerts/listings/push API + check-alerts CLI + poll loop (T5)`.

---

## Task 6: Frontend app shell (5-tab nav + routing) + Vault/Browse polish + Card detail

**Files:**
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/CardDetail.tsx`
- Create: `frontend/src/components/Browse.tsx`
- Modify: `frontend/src/App.tsx` (rewire to AppShell)
- Modify: `frontend/src/api/client.ts`, `types.ts` (card search + detail types; watchlist/alerts/listings/push types go in T7)
- Modify: `frontend/src/styles.css` (5-tab nav + card detail + browse styles)
- Test: `frontend/src/__tests__/CardDetail.test.tsx`, `__tests__/Browse.test.tsx`

**AppShell:** replaces the inline nav in `App.tsx`. 5 tabs: Scan, Vault, Alerts, Browse, More. State `view: "scan" | "vault" | "alerts" | "browse" | "more"`; Alerts is default. Bottom nav shown in standalone PWA (existing convention) AND in-browser (now that there are 5 surfaces, show the nav in-browser too — the prior "header toggle in-browser" pattern doesn't scale to 5; show bottom nav always, keep a slim header with the active title). Unread badge on Alerts tab (fetched via `getUnreadCount`, polled). Each tab routes to its component. Scan tab keeps the existing `CameraCapture` → `ScanResult` → `CardDetail` flow. A `selectedCard` state (card_id + variant) drives `CardDetail`; tapping a Vault holding / Browse result / Alert row sets it and switches to a `detail` view (or renders detail over the current tab).

**Card detail (`CardDetail.tsx`):** props `cardId`, `variant`. Fetches card (catalog endpoint) + grading-upside (`getGradingUpside`, existing) + listings (`POST /cards/{id}/listings`, new) + price history (existing `PriceChart`). Renders: card art (`image_large`), name + set + number, market price + staleness, `GradingUpside` panel (existing component, reused), `PriceChart` (existing), active listings list (empty → "no active listings — set a listings source key" honest state, never fake), and a "Watch this card" button → opens `WatchCardSheet` (T7). Mobile-safe stacked layout.

**Browse (`Browse.tsx`):** debounced (300ms) search input → `GET /cards/search?q=` (add this endpoint to api.py if not present — check; the catalog likely has a search endpoint already; if not, add a minimal `GET /cards?q=` using `func.lower(name).like(f"%{q}%")` limited to 25 results). Results list → tap sets `selectedCard` → Card detail.

- [ ] Step 1: Write `__tests__/CardDetail.test.tsx`:
  - renders card name/set/number + market price + staleness.
  - renders the grading-upside panel (existing component) when present.
  - active listings render when present; empty + `listings_unavailable` → "set a listings source key"; empty + available → "no active listings".
  - "Watch this card" button present when card has a market price (or always; T7 wires the sheet).
- [ ] Step 2: Write `__tests__/Browse.test.tsx`:
  - debounced search: typing "char" → results after debounce; no results → honest empty.
  - tapping a result routes to Card detail (sets selected card).
- [ ] Step 3: Implement `AppShell.tsx`, `CardDetail.tsx`, `Browse.tsx`; rewire `App.tsx`; add client/types entries; add styles.
- [ ] Step 4: Run `npm --prefix frontend test -- --run` → green (existing 65 + new).
- [ ] Step 5: `npm --prefix frontend run build` → clean.
- [ ] Step 6: Commit: `feat(alerts): 5-tab AppShell + CardDetail + Browse (T6)`.

---

## Task 7: Alerts feed + Watch-card sheet + onboarding + More/settings

**Files:**
- Create: `frontend/src/components/AlertsFeed.tsx`
- Create: `frontend/src/components/WatchCardSheet.tsx`
- Create: `frontend/src/components/More.tsx`
- Modify: `frontend/src/api/client.ts`, `types.ts` (watchlist/alerts/listings/push)
- Modify: `frontend/src/App.tsx` / `AppShell.tsx` (onboarding magic moment + push subscription wiring)
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/__tests__/AlertsFeed.test.tsx`, `__tests__/WatchCardSheet.test.tsx`

**Types (`types.ts`):** `Watch`, `AlertEvent`, `Listing`, `PushSubscription` matching the Pydantic models. `AlertType = "restock" | "new_listing" | "price_target" | "auction_ending" | "drop_time"`.

**Client (`client.ts`):** `getWatches`, `createWatch`, `patchWatch`, `deleteWatch`, `getAlerts(unread?)`, `markAlertRead(id)`, `readAllAlerts`, `getUnreadCount`, `refreshListings(cardId, variant)` → `{listings, listings_unavailable}`, `subscribePush(sub)`, `unsubscribePush(endpoint)`. Use `expectJson`/existing patterns.

**AlertsFeed (the HOME):** fetches `getAlerts`, groups by `alert_type` with filter chips (All / Restock / Price / Auction / Drops). Each row: icon by type, message, relative time, deep-link (tap → CardDetail if card_id, else open `url` from context). Unread rows visually distinct; tap marks read. Pull-to-refresh. Empty state (truly empty, no events ever) → sells the capability: "Your personal card-market radar — watch a card to get pinged the moment it restocks, hits your price, or a vending machine drops." + "Watch a card" CTA → opens WatchCardSheet (with no preselected card → user can search/pick). Honest: never fabricate events.

**WatchCardSheet:** props `cardId?`, `variant?`. Alert-type picker (5 radio chips). Conditional fields: `price_target` → target price input; `drop_time` → datetime picker + lead_time_min input; `auction_ending` → auction_window_min input (default 30); `restock`/`new_listing` → no extra fields. "Watch" → `createWatch` with correct JSON. For `drop_time`, works with no listings key (pure datetime) — note this in the sheet ("works without a listings source"). On success: toast + close.

**More (settings):** channel status cards with honest nudges:
- Push: "Enabled" if subscribed, else button "Enable push" → requests Notification.permission + `serviceWorkerRegistration.pushManager.subscribe({applicationServerKey: vapidPublicKey})` (needs the VAPID public key — expose `GET /push/vapid-public` endpoint returning `{public_key}`; add in T5 if not already — ensure it exists). Then `subscribePush`. Without VAPID configured server-side → "Push not configured on the server" honest.
- Email: shows `smtp_from` status — "Set CARDPLATFORM_SMTP_* to enable email" when unconfigured.
- Listings: "eBay — set CARDPLATFORM_LISTINGS_API_KEY to detect restocks/new listings/auctions" when no key.
- Poll interval display (`alert_poll_min`).

**Onboarding magic moment:** first run lands on Scan (camera-first, no setup). After a successful scan with a recognized card + market price, surface a contextual "Watch this card" prompt (Collectr-style). Store a `localStorage` flag so the nudge doesn't repeat indefinitely.

- [ ] Step 1: Write `__tests__/AlertsFeed.test.tsx`:
  - renders events grouped by type; filter chip "Restock" filters to restock events.
  - unread badge / count; tap row marks read (assert `markAlertRead` called).
  - empty state shows the radar copy + CTA; never renders fabricated events.
- [ ] Step 2: Write `__tests__/WatchCardSheet.test.tsx`:
  - selecting "Price target" shows target input; submitting POSTs `{alert_type:"price_target", target_price:40, ...}`.
  - selecting "Drop time" shows datetime + lead inputs; submits `{alert_type:"drop_time", drop_at:"...", lead_time_min:60}`; shows "works without a listings source".
  - selecting "Auction ending" shows window input (default 30).
  - `drop_time` with no listings key still creates (assert no listings fetch required).
- [ ] Step 3: Implement `AlertsFeed.tsx`, `WatchCardSheet.tsx`, `More.tsx`; add client/types; wire onboarding + push in AppShell; add styles.
- [ ] Step 4: Ensure `GET /push/vapid-public` endpoint exists (add to T5's api.py if not — return `{public_key: settings.vapid_public_key or ""}`; empty string = not configured).
- [ ] Step 5: Run `npm --prefix frontend test -- --run` → green (all).
- [ ] Step 6: `npm --prefix frontend run build` → clean.
- [ ] Step 7: Commit: `feat(alerts): AlertsFeed + WatchCardSheet + More + onboarding (T7)`.

---

## Task 8: Site update (roadmap + scroll-animated Alerts section)

**Files:**
- Modify: `site/app/sections/data.ts` (roadmap row for the alerts/watchlist leg of Phase 05)
- Create: `site/app/sections/Alerts.tsx` (scroll-animated, mirrors `Grading.tsx` motion)
- Modify: `site/app/page.tsx` (wire `<Alerts />`)
- Modify: `site/app/globals.css` (Alerts section styles)

**Roadmap (`data.ts`):** Phase 05 currently `planned` ("Deal sniper & sealed EV", "Listings vs. sold comps; rip-vs-flip modelling"). Change to `status: "progress"` with subtitle "Watchlist + restock/price/drop/auction alerts shipped — rip-vs-flip still planned". Keep 05 title. (Do not add a new row; advance 05 to progress, mirroring how 3b handled 03.)

**Alerts section (`Alerts.tsx`):** `"use client"`, GSAP ScrollTrigger scrub (mirror `Grading.tsx`'s pattern: `gsap.context`, `prefers-reduced-motion` → static final state, content visible JS-off). Content: a scroll-scrubbed reveal of the 4 alert types (restock / price target / auction / drop times) as chips that light up on scroll, plus a "channels" row (in-app / push / email). Honest caption: "Alerts fire only while a check runs — set a listings key for restock/new-listing/auction; vending-machine drop times need no key." Mobile-safe.

- [ ] Step 1: Update `data.ts` (Phase 05 → progress). Update `SHIPPED_COUNT` is computed from done rows; 05 is progress not done so count unchanged — verify the headline "N phases. M shipped" still reads correctly (05 progress doesn't change shipped count; it changes the progress count).
- [ ] Step 2: Write `Alerts.tsx` mirroring `Grading.tsx` motion; wire into `page.tsx` after `<Grading />`.
- [ ] Step 3: Add `globals.css` styles for `.alert-types`, `.alert-type.is-done`, `.channels`, reduced-motion block.
- [ ] Step 4: `npm --prefix site run build` → `out/`; copy `out/` → `docs/` (preserve `docs/.nojekyll` and `docs/superpowers/`).
- [ ] Step 5: Commit: `feat(alerts): site roadmap 05 progress + scroll-animated Alerts section (T8)`.

---

## Task 9: Integrate, verify, docs, merge, push, confirm Pages deploy

**Files:**
- Modify: `AI_CONTEXT.md`, `PROJECT.md`

- [ ] Step 1: `backend/.venv/Scripts/python -m pytest -q` → all green (374 + new T1-T5 tests). Spot-check `SELECT count(*) FROM scan_logs` still 105.
- [ ] Step 2: `npm --prefix frontend test -- --run` → green (65 + new T6-T7). `npm --prefix frontend run build` → clean.
- [ ] Step 3: `npm --prefix site run build` → clean; verify `docs/.nojekyll` present and `docs/superpowers/` intact.
- [ ] Step 4: Manual smoke (backend on :8000, frontend on :5173): scan → CardDetail with listings + Watch CTA; watch a card for restock; run `cardplatform check-alerts` → event in Alerts feed + badge; `GET /alerts/unread-count` reflects it. Enable push (if VAPID generated) → subscription stored. Configure SMTP (optional) → email sends. Unconfigured channels show honest nudge, never fake.
- [ ] Step 5: Update `AI_CONTEXT.md` (new § for alerts: tables, providers, engine, notifier, endpoints, CLI, poll loop, frontend shell; test counts updated) and `PROJECT.md` (Phase 05 watchlist/notifications leg shipped, in progress overall).
- [ ] Step 6: Commit docs.
- [ ] Step 7: Branch `phase-3c-alerts` → merge to `main` (fast-forward if clean), push main + branch.
- [ ] Step 8: **Confirm GitHub Pages deploy succeeds** — `gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds` → latest build `built` (not `errored`). The `.nojekyll` fix from the prior session is in place; the new `docs/` must still build cleanly. If it errored, diff `docs/` for a new `_`-prefixed path and fix. Fetch the live URL and confirm the new Alerts section + roadmap "05 … In progress" render.
- [ ] Step 9: Stop the brainstorming visual-companion server if still running.

---

## Self-review (run after writing)

1. **Spec coverage:** Watch/listing/alert/push schema → T1. ListingsProvider+Ebay+Service → T2. Engine 5 types+idempotency → T3. Notifier 3 channels+gen-vapid → T4. API+CLI+poll → T5. AppShell+CardDetail+Browse → T6. AlertsFeed+WatchSheet+More+onboarding → T7. Site → T8. Integrate/verify/deploy → T9. Config covered in T2/T4. All 5 alert types in T3+T7. All 3 channels in T4+T7. Honest empty states in T2/T3/T5/T6/T7. Sacred constraints noted per task. **Gap:** `GET /push/vapid-public` endpoint — flagged in T7 Step 4 (add if missing in T5). **Gap:** catalog search endpoint for Browse — flagged in T6 (add `GET /cards?q=` if not present). Both addressed inline.
2. **Placeholder scan:** No TBD/TODO. Contracts verbatim. Test cases named + asserted.
3. **Type consistency:** `ListingQuote.source` required (no default) — T2. `lowest_price` returns None not 0.0 — T2/T3. `Watch.last_seen_listing_ids` JSON string — T1/T3. `AlertEvent.delivered_inapp` default True — T1. `check_alerts` never raises — T3. `dispatch` never raises — T4. Method names consistent across tasks (`refresh_listings`, `latest_listings`, `has_stock`, `lowest_price`, `previous_listing_ids`, `check_alerts`, `dispatch`). Frontend client method names (`getWatches`, `createWatch`, `getAlerts`, `markAlertRead`, `getUnreadCount`, `refreshListings`, `subscribePush`) consistent T5↔T7.
4. **Ambiguity:** `has_prior_snapshot` gating for restock/new_listing clarified (first poll = baseline, no fire). Price-target re-arm rule specified. Push 410 pruning specified. Email threaded. `pywebpush` dependency decision documented.

Plan complete.