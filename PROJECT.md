# Project: Technology + Trading Cards (Pokémon)

**Owner:** Lucas
**Started:** 2026-07-28
**Status:** Phase 4 (bulk cataloger — many cards per photo) shipped 2026-08-04 — see
[design spec](docs/superpowers/specs/2026-08-04-phase-4-bulk-cataloger-design.md) +
[plan](docs/superpowers/plans/2026-08-04-phase-4-bulk-cataloger.md). Phase 05b (deal alerts + eBay
sold-comps evidence) shipped 2026-08-04 — see
[design spec](docs/superpowers/specs/2026-08-04-deal-alerts-sold-comps-design.md) +
[plan](docs/superpowers/plans/2026-08-04-deal-alerts-sold-comps.md). Phase 05 (deal sniper /
rip-vs-flip) shipped 2026-08-03 — see
[design spec](docs/superpowers/specs/2026-08-03-deal-sniper-design.md) +
[plan](docs/superpowers/plans/2026-08-03-deal-sniper.md). Phase 05c (sealed-product flip-edge)
shipped 2026-08-19 — see
[design spec](docs/superpowers/specs/2026-08-19-sealed-product-ev-design.md) +
[plan](docs/superpowers/plans/2026-08-19-sealed-product-ev.md). Phase 05d (sealed purchase
ledger + profit tracker + Google Sheets sync) shipped 2026-08-20. Responsive UI overhaul (refined
dark-glass identity + desktop sidebar + Framer Motion — phone to any desktop) shipped 2026-08-20 —
see [plan](docs/superpowers/plans/2026-08-20-responsive-ui-overhaul.md). Living UI (Dashboard Home
landing with animated count-up KPIs + allocation donut + movers; Cmd/Ctrl+K command palette +
keyboard shortcuts; toast system; animated gradient mesh) shipped 2026-08-20 — see
[plan](docs/superpowers/plans/2026-08-20-living-ui.md). Grading Studio (an honest
user-assisted grade-band calculator — measured centering ceiling + user corner/edge/surface
sub-scores → estimated grade, confidence, binding, caveats; the transparent form of the grade
predictor, since a learned one is impossible with 0 labelled scans) shipped 2026-08-21 — see
[plan](docs/superpowers/plans/2026-08-21-grading-studio.md). Set-completion optimizer
(Phase 06 — per-set owned/missing checklist + honest cost to complete via `latest_price`) shipped
2026-08-22 — see [plan](docs/superpowers/plans/2026-08-21-set-completion.md).
Next: rip EV (expected pull value — blocked on pull-rate data + a sealed-product master) or
the full Grade predictor (corner/edge/surface + P(grade), pending labelled-data accrual).

**Shape:** ONE platform built in phases, not seven apps. All modules share a card-recognition core,
a pricing layer, and a collection store. Responsive PWA (phone + desktop): React/TypeScript
frontend, Python/FastAPI backend.

**Public site:** `docs/index.html`, served via GitHub Pages.

## Vision

An app/site at the intersection of **technology and trading cards — primarily Pokémon**.
The bar: something *novel* (nobody has built it, or existing tools do it poorly) that is also
*fun* and *technically ambitious* — a deliberate excuse to work with AI, computer vision / photo
recognition, and techniques not tried before.

Background: this succeeds the ForexAI scanner work. FX turned out to be an efficient market with
no findable short-horizon edge. Collectibles are the opposite — an **inefficient** market where a
real edge exists (mispriced listings, grading arbitrage, EV on sealed product). The market-scanner
instincts transfer; the market is finally one where they can win.

## Guiding principles

- Novel or 10x better than what exists — not another basic price-lookup app.
- Lean into hard tech: computer vision, ML, AI decisioning.
- Start with ONE sharp idea, scoped to ship; expand later.
- "Is this a good deal vs. real market value?" is connective tissue that could later extend to
  Lucas's other hobbies (3D printer parts, PC/electronics, camera gear).

## Phase roadmap

Each phase ships independently usable functionality and gets its own spec → plan → build cycle.

| Phase | Module | Status |
|---|---|---|
| 0 | Foundation — card catalog, pricing layer, collection store | **Complete** |
| 1a | Recognition engine — photo → identified, valued card (API) | **Complete** |
| 1b | Scan PWA — camera capture, top-3 picker, scan logging | **Complete** |
| 1c | Robust card detection — coverage 31% → 61%, 0 regressions | **Complete** |
| 2 | Portfolio tracker — cost basis, P/L, price charts | **Complete** — ships correct, useful as data accrues |
| 3a | Card centering — geometric PSA cap from border measurement | **Complete** |
| 3b | Grading data infrastructure — rectified-crop persistence, grade-label schema + self-annotation, graded-price provider, grading-upside spread | **Complete** |
| 3c | Watchlist + restock/price/drop/auction alerts — CollectorVault-style 5-tab UI | **Complete** |
| 3 | Grade Predictor — corner/edge/surface scoring + P(grade) + grading EV | In progress — data infra unblocked (3b); full predictor still planned |
| 4 | Bulk cataloger — detect every card in one photo | **Complete** |
| 5 | Deal sniper + sealed EV — listings vs. sold comps, rip-vs-flip | In progress — deal sniper / rip-vs-flip + deal alerts + sold-comps evidence shipped; sealed flip-edge shipped; sealed purchase ledger + profit tracker + Google Sheets sync shipped; rip EV (expected pull value) still planned — needs pull-rate data |
| 6 | Set-completion optimizer — cheapest path to finish a set | **Complete** — per-set owned/missing checklist + honest cost-to-complete via `latest_price`; 10th Sets tab + SetDetail overlay shipped 2026-08-22 |
| 7 | Counterfeit detector — holo pattern, rosette, texture analysis | Planned |
| 8 | On-device inference — quantized model in-browser, no server | Planned |

## Key decisions

- **Local-first.** All inference runs on Lucas's own machine (RTX 5070 Ti / 16 GB VRAM). Only the
  catalog + price sync touches the network, so scanning works offline.
- **Data source verified 2026-07-28.** `pokemontcg.io` supplies free **per-variant** pricing
  (holofoil vs. reverse-holofoil priced separately — exactly what variant disambiguation needs),
  TCGplayer refreshed daily. But the **API is badly degraded (2/12 requests succeeded)**, so the
  catalog is bulk-loaded from the [`pokemon-tcg-data`](https://github.com/PokemonTCG/pokemon-tcg-data)
  JSON dump instead, and all providers sit behind an interface so a fallback can be swapped in.
- **Setup hazards:** system Python is 3.14 (too new for the ML wheels — use a 3.12 venv), and
  Blackwell GPUs need a CUDA 12.8+ PyTorch build or they silently fall back to CPU.

## Phase 0 — shipped

Built 2026-07-29 ([plan](docs/superpowers/plans/2026-07-28-phase-0-foundation.md)). **69 tests passing.**

- **Catalog:** 174 sets, **20,444 cards** loaded locally from the
  [`pokemon-tcg-data`](https://github.com/PokemonTCG/pokemon-tcg-data) JSON dump. Sync is idempotent
  and resumable (commits per set), so a dropped connection mid-run costs one set, not the whole load.
- **Prices:** per-variant snapshots from pokemontcg.io behind a swappable provider interface,
  retry-hardened with backoff. Terminal errors (404/401) are not retried; 5xx and 429 are. Snapshots
  are immutable and deduped, so price history accrues from day one.
- **Collection:** add/remove/list with deliberately conservative valuation — an unpriced item counts
  as zero and is reported separately rather than guessed at.
- **API:** FastAPI over catalog, prices, and collection. Every price carries its `source` and
  `source_updated_at`.
- **Stack note:** SQLite via SQLAlchemy ORM (no SQLite-specific SQL), so a Postgres swap stays cheap.

**Why staleness is surfaced rather than blended** — real data for `base1-4` on 2026-07-29:
cardmarket said **$1531.00** (updated 07/01), tcgplayer said **$800.43** (updated 07/29). Nearly 2×
apart. Collapsing those into a single "market price" would be actively misleading, so the API never
does.

## Phase 1a — shipped

Recognition engine built 2026-07-29
([plan](docs/superpowers/plans/2026-07-29-phase-1a-recognition-engine.md)). **155 tests passing.**

Photo → rectify → CLIP embedding search over a FAISS index of **20,391 cards** → targeted OCR of the
collector number → fused into a calibrated decision. Served at `POST /recognize`, returning the card,
its price with staleness stamp, and ranked candidates when uncertain.

### Measured accuracy at full index scale

3,000 queries (500 cards × 6 degradations) against all 20,391 cards:

| Condition | top-1 | top-3 |
|---|---|---|
| clean | 99.8% | 99.8% |
| jpeg q35 | 98.0% | 99.6% |
| dim (55% brightness) | 99.0% | 99.8% |
| glare overlay | 99.2% | 99.8% |
| blur (σ1.6) | 89.0% | 97.2% |
| **combo** (all stacked) | **85.4%** | 93.8% |

Blur is the weak spot; everything else clears 98%. The earlier "~85% at full scale" projection turned
out to describe the *stacked worst case*, not the typical one.

### Why the hybrid design earns its keep

Margin (top score minus runner-up) separates correct from incorrect matches **13.7×** — 0.1201 vs
0.0088. That is what makes calibrated confidence possible rather than guesswork.

`min_margin` is set to **0.05**: 78.8% of scans auto-confirm at 100% precision (1 wrong in 3,000).
The calibration harness recommended 0.02 (89.9% auto, 14 wrong), but a confidently wrong
identification is far worse for this product than one extra "which of these three?" prompt.

Visual search alone confuses same-name reprints — a live scan of Base Charizard returns `base6-3` and
`base4-4` Charizards at 0.901 and 0.873 behind the correct 0.991. The collector number resolves
exactly those, which is why OCR is load-bearing rather than decorative.

### Known limitation

**Every number above comes from degraded reference images, not photographs of physical cards.** Real
photos add perspective, uneven lighting, background clutter, and foil glare that no augmentation
here simulates. Phase 1b starts by collecting real phone photos and re-running the harness — that is
the honest accuracy figure.

Rectification is also known to fail on pale backgrounds and edge-clipped framings; it now rejects
non-card-shaped quads rather than silently returning a stretched crop of the card's artwork.

## Phase 1b — shipped, and what it measured

Scan PWA built 2026-07-30
([plan](docs/superpowers/plans/2026-07-29-phase-1b-scan-pwa.md)). React + TypeScript, served over
HTTPS (mandatory — `getUserMedia` refuses to run otherwise), proxying to the FastAPI backend.

**99 real scans of physical cards, 39 reviewed.** This is the first accuracy figure not derived from
reference images, and it reframes what the project's actual problem is.

| Status | scans | reviewed | correct | precision |
|---|---|---|---|---|
| **confident** | 30 | 29 | **29** | **100.0%** |
| ambiguous | 13 | 10 | — | declined, user picked |
| **not_found** | **56** | — | — | never detected a card |

### The two findings that matter

**1. Recognition is not the problem. Detection is.**

When the pipeline committed to an answer it was right **29 out of 29**. Zero confidently wrong
identifications on real photographs. The `min_margin = 0.05` calibration — chosen over the harness's
0.02 recommendation precisely to avoid confident errors — held up under real conditions.

The signal separation survived the jump from reference images to phone photos:

| | mean confidence | mean margin |
|---|---|---|
| correct | 0.953 | **0.0866** |
| wrong | 0.820 | **0.0205** |

**But 57% of scans never got past finding the card in the frame.** Diagnosed across 20 failures:
**no 4-point quad was found at all in 20 of 20** (mean large-contour count 0.4). It is not the aspect
gate rejecting a wrong shape — there is nothing to reject. In 20 successful scans the detected quad's
median aspect was 1.40, exactly a card.

Brightness was near-identical between the two groups (89 vs 96 of 255), so it is not darkness. It is
**edge contrast**: Canny needs a closed boundary, and a light card border against a light background
never forms one. Hence the user-observed rule that a black background is required.

Re-running 25 failed images with detection bypassed produced **ambiguous, not not_found** — the cards
are recognizable, but an uncropped frame dilutes the embedding below the confidence threshold.
Detection is squarely the bottleneck.

**2. The headline "74.4%" is a bad metric and should not be quoted.**

`ScanStore.accuracy()` counts an ambiguous result the user resolved as "wrong", because the pipeline
made no prediction to be right about. That conflates *declining to guess* with *guessing wrong* —
which are the opposite of each other in a system built around calibrated uncertainty. The honest
pair of numbers is **100% precision at 30% coverage**.

### Carried into Phase 1c

- **Card detection is the single highest-value fix.** Canny + external contours is too fragile for
  varied backgrounds. Worth trying: adaptive thresholding, saturation-based segmentation, or a
  learned segmentation model, with a multi-strategy fallback chain.
- **A manual corner-drag fallback** for when automatic detection fails — anticipated in the design
  spec and now clearly justified.
- **Sleeved cards are inconsistent** (user-reported): glare and the sleeve's own edge both interfere.
- **Fix the accuracy metric** to report precision and coverage separately.
- On-demand price fetches were measured at **27 s** in one live test, far worse than the 4.3 s mean
  seen earlier. The decoupled price line handles it, but the interactive path may want a lower retry
  ceiling than the batch path.

## Phase 1c — shipped

Robust card detection, built 2026-07-30
([plan](docs/superpowers/plans/2026-07-30-phase-1c-robust-detection.md)). **207 backend tests,
22 frontend tests.**

### Measured by replaying all 101 real scans

| status | before | after |
|---|---|---|
| confident | 31 | **62** |
| ambiguous | 13 | 36 |
| **not_found** | **57** | **3** |

**Coverage 31% → 61%. Zero regressions** — not one scan that was previously identified correctly
now returns a different card. `not_found` fell from 57 to 3.

### What actually fixed it

Two compounding causes, both diagnosed on the real failures:

1. **Canny needs a gradient, not a level.** A light card border on a light background forms no closed
   contour — the reason a black background was required.
2. **`approxPolyDP` demands exactly 4 vertices.** Real photos have rounded corners and sensor noise,
   so it lands on 5–7 and discards a visible card. Fitting a **rotated rectangle** to the largest
   blob drops that requirement — a card *is* a rectangle.

The design is a **strategy chain scored by recognition**: each strategy proposes a quad, every
proposal is embedded (2.2 ms), and the crop that actually matches best wins. OCR runs once, on the
winner, because it costs ~1 s. This matters because a single better detector was *not* strictly
better — `otsu_rect` alone recovered 33 failures but regressed 6 working scans. The chain regresses
none.

### A research error worth recording

The original detector comparison credited `adaptive_rect` with 56/56. It was wrong. Adaptive
thresholding returned a **whole-frame quad on all 101 real scans** — never once a card — and the
image border's aspect ratio (1.29 on a portrait photo) passed the shape gate. "Found a quad" was
being counted as "found the card", the exact trap the aspect gate exists to prevent.

Fixed with a `MAX_AREA_FRACTION = 0.98` guard, after which the strategy contributed **0 usable
proposals** and was removed. Real card detections measure 0.15–0.44 of the frame. The live chain is
`canny` + `otsu_rect`; on 101 scans canny proposed 43 times and otsu_rect 98.

### Also in this phase

- **Manual corner drag** — the user places four corners when detection still fails. Corner-adjusted
  scans are logged identically, so the fallback's value shows up in the accuracy stats.
- **The accuracy metric was replaced.** It reported 74.4% for a pipeline that was right 30/30 on
  reviewed predictions, by counting a *declined* result as a *wrong* one. It now reports
  **precision 1.000 at 30.7% coverage** on the same data — separately, as it should always have been.

### Known limitations

- 36 scans still return `ambiguous` — detected but not confidently matched. That is a *recognition*
  problem, and the honest next lever is fine-tuning the encoder on the corrections collected since
  Phase 1b.
- The corner-drag interaction is verified by type-check only; jsdom has no layout, so pointer capture
  and handle positioning need a real device pass.
- A corner-adjusted retry writes a second scan row, mildly deflating measured coverage.
- Sleeve glare remains unquantified.

## Where recognition actually stands (measured 2026-07-30)

Replaying all 101 saved real scans through the current pipeline:

| | coverage | regressions |
|---|---|---|
| before Phase 1c | 31% | — |
| after multi-strategy detection | 61% | 0 |
| after OCR sharpening | **63%** | **0** |

**And on the 40 labelled scans, the true card ranks:**

| position | cumulative |
|---|---|
| rank 1 | **88%** |
| top 3 | **98%** |
| not in top 5 | 1 scan |

So with the candidate picker, nearly every scan is resolvable by the user even when the pipeline
declines to commit. Precision when it does commit remains 100%.

### OCR preprocessing, measured over 39 real rectified crops

A read counts as correct only if it matches the card's true collector number. A *wrong* number is
worse than none, because fusion may act on it:

| variant | correct | wrong |
|---|---|---|
| plain 3× upscale (previous) | 21 | 6 |
| 5× upscale | 19 | 6 |
| CLAHE + 4× | 22 | 6 |
| **sharpen + 4× (shipped)** | **24** | **3** |
| taller strip + 4× | 24 | 12 |

### The remaining gap

34 scans are `ambiguous` — detected, but not confidently matched. Diagnosed: **OCR read a number in
only 5 of 11** sampled, with a mean visual margin of 0.023 against a 0.05 threshold. These are narrow
visual calls a collector number would settle. OCR reliability, not the encoder, is the next lever.

## Phase 2 — shipped

Portfolio tracker, built 2026-08-01
([plan](docs/superpowers/plans/2026-08-01-phase-2-portfolio.md)). **276 backend tests, 47 frontend
tests.** Turns the collection from a flat holdings list into a portfolio: per-item market value and
unrealised P/L, an allocation-by-set + top-movers summary, cost-basis editing and removal, and a
price-history chart.

### Measured findings the build rested on (verified 2026-08-01)

- `CollectionItem` already had `acquired_price`, `acquired_at`, `notes`, `condition`, `variant`,
  `quantity` — the columns existed but were unused by the store/API. No migration needed.
- `CollectionStore.add` merged rows on `(card_id, variant)` and never stamped `acquired_at`; the 37
  existing rows had `acquired_at IS NULL` and could not be backfilled through `add`.
- The append-only `PriceSnapshot` table was already shaped for history (`uq_snapshot(card_id, source,
  variant, source_updated_at)`); only the query was missing.
- **0 of 37 collection items have a cost basis; 0 price series have more than one distinct
  `source_updated_at`.** The data has not yet accrued — so the build's job is to be *correct now* and
  become useful as data lands, not to fabricate trends.

### Endpoints shipped

- `GET /collection/portfolio` — priced holdings + summary (allocation, top movers, priced/unpriced
  counts) in one round trip. All valuation is server-side via `PriceService.latest_price`; the client
  never resolves "the latest price" itself.
- `GET /cards/{id}/prices/history?variant=&days=` — one point per `source_updated_at`,
  tcgplayer-preferred, each point carrying its own `source` + `source_updated_at`. Never blends
  sources into one canonical number.
- `PATCH /collection/{id}` — cost basis / `acquired_at` / `condition` / `notes`.
- `DELETE /collection?card_id=&variant=&quantity=` — decrements, deletes the row at zero.
- `add` now stamps `acquired_at` on new rows only (a top-up is not a new purchase).

### The honest-empty-states decision

This is the same "never fake missing data" value the em-dash-for-missing-cost-basis already encoded,
generalised across the portfolio:

- A chart with one snapshot renders a **single dot** and says "need more history to draw a trend" —
  never a fabricated trend line.
- P/L with no cost basis renders an **em dash**, never `+$0.00` and never market value dressed up as
  profit.
- An unpriced holding shows `—` + "no market price", never `$0.00`.
- A series observed but never priced says "Unpriced" — never a flat zero line that would imply the
  card is worthless.
- The chart is hand-rolled inline SVG (zero chart libraries), matching the project's minimal-deps
  ethos.

### Out of scope (deliberately deferred)

- **Lot-level collection model** — re-adding the same `(card, variant)` still tops up one row and
  ignores the new `acquired_price`; a per-purchase lot model is deferred.
- **Source blending** — each history point carries its own `source`; the chart plots the
  tcgplayer-preferred resolved point per date but never invents a blended "market price" number.
- **Predictive trends / projections** — the chart plots observed points only.

## Phase 3a + 3b — shipped

**3a — card centering** (2026-07-31): a geometric PSA *cap* from front-border measurement — always a
ceiling ("centering allows up to PSA 9"), never a grade. Correct by construction (0.00% error on
synthetic cards) but only ~4% coverage on real photos (textured modern frames defeat the border
classifier); the 101 saved scans are the test set to fix coverage against. Corners, edges and surface
are not assessed.

**3b — grading data infrastructure** (2026-08-01, branch `phase-3b-grading-infra`). **374 backend +
65 frontend tests.** Unblocks the full Grade predictor by building the infrastructure to collect the
labelled data it needs and the graded-price leg — without shipping a fake prediction. 105 real scans
preserved; raw `PriceSnapshot` and recognition behavior untouched.

- **Migration helper** (`db/migrations.py`) — idempotent nullable-ALTER, no Alembic; new tables
  `grading_labels` + `graded_price_snapshots`, new `scan_logs.rectified_path` + `variant`.
- **Rectified-crop persistence** — the 600×825 rectified PNG is written to `data/rectified/` and
  stamped on the scan log; the normalized input a future corner/edge/surface grader consumes.
- **Grade-label store + self-annotation API** — `POST/GET /scans/{id}/grade-label`,
  `GET /grading/labels`; the only honest labelled dataset is the user's own mailed-in grades.
- **Graded-price provider + service** — `PkmnPricesProvider` (env-keyed, degrades to `[]` without a
  key, never raises) + `GradedPriceService`; CLI `refresh-graded-prices`. Documented follow-ups:
  PkmnPrices↔`base1-4` id mapping; pagination.
- **Grading-upside spread** — `GET /cards/{id}/grading-upside?variant=` returns raw / PSA-9 / PSA-10
  comps + fee + `upside_to_10` (null unless both inputs present) + `graded_prices_unavailable`. A
  **spread, not a prediction** — P(grade) needs the labelled dataset we're only starting to collect.
- **Frontend** — `GradingUpside` panel (honest empty states: `—` + "no market price",
  graded-unavailable → the API-key hint, never `$0.00`) + a `ScanResult` self-annotation form.
- **Site** — new scroll-animated Grading section (Centering lit; Corners/Edges/Surface dimmed with
  "Needs labelled data" tags that never light up) + roadmap row 03b; rebuilt → `docs/`.

## Phase 3c — shipped

Watchlist + notifications, built 2026-08-02
([spec](docs/superpowers/specs/2026-08-02-alerts-watchlist-design.md) +
[plan](docs/superpowers/plans/2026-08-02-alerts-watchlist.md)). **443 backend + 90 frontend tests.**
A CollectorVault-inspired 5-tab app shell (Scan/Vault/Alerts/Browse/More, Alerts-first) over a new
watchlist + notification engine. The same "never fake missing data" value throughout: the feed never
invents events, listings degrade honestly when no source key is set, and channels degrade silently
when unconfigured. 105 real scans preserved; raw price/graded tables and recognition untouched.

- **5 alert types, all idempotent** — `restock`, `new_listing`, `price_target` (cooldown +
  re-arm), `auction_ending` (per-listing dedupe), `drop_time` (lead reminder + drop, then stops).
  Restock/new_listing diff off a per-watch `last_seen_listing_ids` JSON baseline — not the listings
  service — because immutable snapshots make empty fetches invisible. First poll fires nothing.
- **Never-raise engine** — `AlertEngine.check_alerts()` wraps each watch in a SAVEPOINT so a flush
  `IntegrityError` is isolated; per-watch try/except + a wrapped final commit. Regression-tested.
- **Three delivery channels, each degrades independently** — in-app (always on), web push
  (`pywebpush` + VAPID, prunes 404/410), email (`smtplib`, `timeout=10`, SMTPS 465 / STARTTLS 587 /
  plaintext 25). `NotificationService.dispatch` never raises.
- **Listings leg** — `ListingsProvider` Protocol + `EbayListingsProvider` (mirrors the graded-price
  provider: degrades to `[]`, never raises) + `ListingsService` (immutable `ListingSnapshot` dedupe,
  `lowest_price` is None not 0.0). Honest `listings_unavailable` flag in the API.
- **12 endpoints** — watchlist CRUD (422 validation per alert type), alerts feed + read/read-all +
  unread-count, per-card listings, push subscribe/unsubscribe + vapid-public. A startup poll loop
  runs the engine every `alert_poll_min` (15) minutes; CLI `check-alerts` for a one-shot run,
  `gen-vapid` for the VAPID keypair.
- **Frontend** — `AppShell` 5-tab nav; `CardDetail` reuses GradingUpside + charts with honest listing
  empty states; `AlertsFeed` (type-filter chips, unread accent, mark-read + deep-link, honest radar
  empty state); `WatchCardSheet` bottom sheet (5 alert types, conditional fields, client-side
  validation mirroring the 422 rules); `More` (honest channel cards + watchlist management).
- **Site** — new scroll-animated Alerts section (5 alert chips, GSAP scrub + Framer reveal,
  reduced-motion fallback, honest "alerts fire only while a check runs" caption) + roadmap row 05 →
  in-progress ("…alerts shipped — rip-vs-flip modelling still planned"). Rebuilt → `docs/`.

**Documented follow-ups** — `@app.on_event` poll loop is deprecated-cosmetic (lifespan handler is
the clean replacement); the eBay listings adapter was upgraded to the real Finding API in Phase 05
(see below) — restock/new_listing/auction alerts now flow when `CARDPLATFORM_LISTINGS_API_KEY`
(eBay App ID) is set; `previous_listing_ids` can merge same-clock-tick fetches (fine at a 15-min
cadence).

## Phase 05 (deal-sniper leg) — shipped

Deal sniper / rip-vs-flip, built 2026-08-03
([spec](docs/superpowers/specs/2026-08-03-deal-sniper-design.md) +
[plan](docs/superpowers/plans/2026-08-03-deal-sniper.md)). **462 backend + 96 frontend tests.**
Joins the 3b graded-price leg and the 3c listings leg into one evaluation: **is this active listing a
deal — to rip (buy below raw sold-comp market) or to flip (buy raw, grade, sell at the PSA-10 comp)?**
The same "never fake missing data" value throughout — missing raw/graded nulls the edge it feeds
(never `$0`, never a fake profit). 105 real scans preserved; raw price/graded tables and recognition
untouched.

- **Deal model (read-only `DealEngine`)** — `rip_edge = raw_market − listing.price`;
  `flip_edge_to_9/10 = psa comp − listing.price − grading_fee`. `is_rip` iff `rip_edge >= $2` AND `>=
  10% of raw market; `is_flip` iff `flip_edge_to_10 >= $20`. `deal_score = max(rip, flip-to-10)`,
  ranked desc nulls last. **Writes nothing** — deals are computed on demand from the latest
  snapshots, so they never go stale in storage (no `deal_snapshots` table). Edges are indicative
  leads; the UI says "investigate before buying".
- **eBay Finding API adapter (the realness leg)** — the 3c `EbayListingsProvider` called the Browse
  API with the key faked as a static bearer (Browse needs real OAuth, so it never returned
  listings). Replaced with the Finding API `findItemsByKeywords`: one `SECURITY-APPNAME` (eBay App
  ID) query param, no OAuth. A catalog lookup (card name + number) wired into the API + CLI +
  poll-loop paths — **this also unblocks the 3c restock/new_listing/auction alerts**. Never-raise
  discipline kept; price-less items skipped not fabricated; `auction_end_at` only for auctions.
- **API + CLI** — `GET /cards/{id}/deals?variant=` (ranked, honest `listings_unavailable` /
  `listings_empty` flags, thresholds in response) + `GET /deals?card_ids=&limit=` (cross-card feed
  defaulting to the watchlist) + `cardplatform find-deals` CLI (honest no-key / no-listings
  messages).
- **Frontend** — 6th bottom-nav **Deals** tab (`Deals.tsx` — search or pull watched cards → ranked
  deal feed, rip/flip edges, deal chips, staleness, "investigate before buying" caveat; honest
  empty states) + per-listing deal-score chips on `CardDetail`.
- **Site** — new scroll-animated `Deals` section (rip-vs-flip diagram, GSAP scrub + Framer reveal,
  reduced-motion fallback) with the honest "indicative leads, not guaranteed arbitrage — always
  verify the listing" caption; roadmap row 05 → in-progress. Rebuilt → `docs/` (`.nojekyll` +
  `docs/superpowers/` preserved).

**Key acquisition** — free eBay developer account → My Apps → create app → the App ID is the
`SECURITY-APPNAME`, set as `CARDPLATFORM_LISTINGS_API_KEY`. Until set, the whole deal surface is
honestly empty — the phase ships regardless.

**Documented follow-ups** — sealed-product EV (Phase 05's other leg, needs a sealed-product price
provider); deal snapshots / history; multi-source listings (only eBay; the Protocol keeps a second
source swappable); full-catalog deal scan; eBay OAuth / Browse API as an upgrade path. (Deal alerts
+ sold-comps evidence shipped in Phase 05b, below.)

## Phase 05b (deal alerts + sold-comps evidence) — shipped

Deal alerts + eBay sold-comps evidence, built 2026-08-04
([spec](docs/superpowers/specs/2026-08-04-deal-alerts-sold-comps-design.md) +
[plan](docs/superpowers/plans/2026-08-04-deal-alerts-sold-comps.md)). **485 backend + 102 frontend
tests.** Two additive legs on top of Phase 05 — both hold the sacred constraints: no schema change,
no new table, no snapshot writes. 105 real scans preserved; raw price/graded/listing tables and
recognition untouched.

- **Deal alerts (push instead of pull)** — composes the 3c `AlertEngine` with the Phase 05 read-only
  `DealEngine` so a *new* active listing clearing the rip/flip thresholds fires an alert. A `deal`
  watch fits the existing `Watch` model with **no new columns / no migration** (`alert_type="deal"`,
  unique key `(card_id, variant, "deal", None, None)`; global `deal_*` thresholds). `AlertEngine`
  gains an optional `deal_engine=None` collaborator; `_eval_deal` mirrors `_eval_new_listing`'s
  `last_seen_listing_ids` baseline dedupe — **first poll never fires**, fires only for NEW listings
  clearing rip/flip, baseline always advances. Watchlist API: `_ALERT_TYPES` += `"deal"`, 422 if
  `card_id` missing. The poll loop + `check-alerts` CLI inject the shared `DealEngine`.
- **eBay sold-comps evidence** — `EbayListingsProvider.fetch_sold_listings` via the Finding API
  `findCompletedItems` (`SoldItemsOnly=true`, `SERVICE-VERSION=1.13.0` — the `EndedWithSales` bug
  fix, `EndTimeSoonest`) → the 3 most-recent eBay SOLD listings as **on-demand evidence** backing the
  raw market price. **NOT persisted** — no snapshot writes, no `SoldCompSnapshot` table. `_parse_completed`
  skips anything whose `sellingState != "EndedWithSales"` and any price-less item (never fabricate a
  sale). `GET /cards/{id}/sold-comps?variant=&limit=3` with honest `sold_comps_unavailable` /
  `sold_comps_empty` flags; `SoldComps.tsx` rendered under the market price in `CardDetail`.
- **Frontend** — `WatchCardSheet` gains a 6th Deal chip; `AlertsFeed` gains a Deals filter chip +
  💰 icon; `SoldComps` evidence block with honest empty states.

**Deprecation caveat** — eBay deprecated `findCompletedItems` on 2020-10-15 (Marketplace Insights
API is the documented successor, but Limited Release / not viable for a solo free-tier app). The
deprecated endpoint still responds for free App IDs today; the adapter degrades to `[]` on any
failure and the UI shows an honest "recent sold comps unavailable" — so shipping behind it is safe.
Marketplace Insights migration is a documented follow-up, not this phase.

**Sacred constraints held** — no ad-hoc price resolution; no snapshot writes for sold comps; no
schema change / no new table; staleness surfaced (`sold_at`); honest empty states (no `$0`, never a
fabricated sale, never a fabricated deal event); no `data/` deletion; snapshots still immutable.

## Phase 4 (bulk cataloger) — shipped

Bulk cataloger — many cards per photo, built 2026-08-04
([spec](docs/superpowers/specs/2026-08-04-phase-4-bulk-cataloger-design.md) +
[plan](docs/superpowers/plans/2026-08-04-phase-4-bulk-cataloger.md)). **505 backend + 106 frontend
tests.** One binder-page photo → N identified + valued cards in one scan, with a batch review grid
where each card is fixed up independently (corner drag, candidate pick, per-card variant) and
bulk-added to the collection. Additive to the single-card pipeline — `POST /recognize` +
`detect_candidates` are byte-for-byte unchanged, and the 105-scan baseline replays with **0
regressions**. No external API added this phase.

The phase splits **detection** (run once → N non-overlapping quads via IoU NMS) from **recognition**
(per-quad, batched embedding, parallel OCR):

- **Multi-quad detection + IoU NMS** — `detect_all_quads` collects every card-shaped contour from
  `canny` + `otsu_rect` (both Otsu polarities), IoU-NMS-dedupes (no NMS existed anywhere before) → N
  quads largest-first. `MAX_AREA_FRACTION=0.98` is kept (rejects the whole-frame blob adaptive
  thresholding made on 101/101 real scans); a binder card is ~0.11 of a 9-card frame.
- **Batched recognition** — `recognize_many` rectifies each quad, calls `embed_many` **once** (the
  encoder already supported batching), searches the index per vector, then fuses + OCRs each winning
  crop. OCR (~1 s/crop) is parallelized across a per-worker reader pool — one `copy.deepcopy` reader
  per worker because RapidOCR is not thread-safe. **Recognition is still the arbiter, not geometry:**
  a card-shaped sleeve/glare slot still embeds low and stays `not_found` per crop, never auto-promoted.
- **Batch scan logging** — additive nullable `scan_logs.batch_id` (indexed) + `batch_index` via the
  idempotent migration helper (the 105 existing rows stay NULL). `ScanStore.record_batch` writes the
  source photo once → N rows sharing `image_path`, per-crop commit, logs `not_found` too. `accuracy()`
  is batch-aware: one representative per `batch_id`; NULL-`batch_id` rows are singleton batches, so the
  105-scan baseline is NOT inflated.
- **`POST /recognize/batch`** — mirrors `POST /recognize` field-for-field: `detect_all_quads` → cap
  `max_cards` (default 9, clamped `[1,18]`) → `recognize_many` → `latest_price` per confident card →
  `BatchRecognizeOut{batch_id, count, results: [RecognizeOut]}`. Per-card statuses are NEVER collapsed
  into one batch status; `not_found` → `card/price` null, never `$0`. The endpoint does NOT write
  `scan_logs` — the client logs per card via `POST /scans` threading `batch_id`+`batch_index`.
- **Batch review grid** — `BulkPane`: single↔bulk toggle in the Scan pane (default single; single-card
  branch verbatim), one binder-page capture → CSS grid of N `ScanResult` cells (reused unchanged) with
  per-cell variant selector + fix-ups, bulk-add to collection (duplicates merge). `formatMoney(null)` →
  `—`, never `$0.00`.
- **Eval harness** — `make_batch_fixtures.py` (synthetic 3×3 + 2×2 binder pages with per-card
  ground-truth JSON) + `evaluate_detection.py --batch` (per-card IoU>0.5 recall, fails if any page
  <0.8). Recall 1.00 on both fixtures. Two harness fixes in T7: the script now calls
  `database.create_all()` at startup (it opened a stale DB lacking the T3 column — `select(ScanLog)`
  500s without the migration; the app/cli self-heal but the script didn't) and unpacks `recognize()`'s
  `(result, centering)` tuple (a pre-existing Phase 3a breakage — the harness hadn't been run since
  centering was added). Neither was a Phase 4 regression.

**Open questions resolved (auto-mode defaults)** — synthetic fixtures (real binder capture is a
documented follow-up); extend canny+otsu_rect+IoU NMS (defer line/segment grid); `batch_ocr_workers`
default 2 clamped `[1,4]`; all N rows share the source `image_path`; `max_cards` default 9 clamped
`[1,18]`; default `normal` variant + per-cell selector; bulk-add merges duplicates (per-lot cost-basis
deferred from Phase 2); in-pane mode toggle (not a 7th nav tab); per-crop commit.

**Documented follow-ups** — line/segment grid detection (measured follow-up if blob+NMS underperforms
on real binder photos); real-binder fixture capture (synthetic only this phase); per-lot cost-basis
model (still deferred from Phase 2); persisting a parent batch row (the shared `batch_id` +
`batch_index` on each row is sufficient grouping); auto-rotating/flattening the binder page.

**Sacred constraints held** — no ad-hoc price resolution (only `latest_price`); honest empty states
(no `$0`, never a fabricated card or status, per-card statuses never collapsed); snapshots immutable;
no `data/` deletion (only additions under `data/scans/batch_fixtures/`); additive schema only
(nullable columns via the idempotent migration helper, 105 rows stay NULL); recognition is the
arbiter; single-card path unchanged; 105-scan baseline 0 regressions.

## Carried into Phase 1 (from the final Phase 0 review)

Verified against the real 20,444-card database — resolve these when planning Phase 1:

**Data facts that affect the image pipeline**
- **0 cards have a missing `image_small`**, 0 duplicates, 0 orphan `set_id`s. The catalog is clean
  enough to build the embedding index on directly.
- **Images span two CDNs** — 19,783 on `images.pokemontcg.io`, 661 on `images.scrydex.com`. The
  post-acquisition migration is visibly in progress.
- **661 URLs have no file extension**, ending in `/small` rather than `.png`. Any cache-filename
  logic doing `url.rsplit(".", 1)[-1]` breaks on 3% of the catalog.

**Gaps to close before the scan loop works end to end**
- **Only 2 of 20,444 cards have any price snapshot.** Prices arrive solely via
  `cardplatform refresh-prices <ids>`. A scan of an arbitrary card returns "unpriced" until there is
  a bulk backfill job or an on-demand `POST /cards/{id}/prices/refresh`.
- **No HTTP endpoint returns the *resolved* price.** `GET /cards/{id}/prices` returns every
  `(source, variant)` pair; the "which one is *the* price" rule lives only in
  `PriceService.latest_price`. Add `GET /cards/{id}/price?variant=…` so the scan UI does not
  reimplement it client-side.
- **`variant` is unvalidated free text.** A recognizer emitting `"reverse_holo"` instead of
  `"reverseHolofoil"` silently creates a row that can never be priced correctly.
- **`latest_price` hardcodes `"tcgplayer"` / `"cardmarket"` / `"aggregate"`**, so a second provider
  would persist snapshots yet stay invisible to valuation. Worth fixing before Phase 5 adds a source.
- Nowhere to record match confidence or the source photo for a recognized card.
- `cli.py` has 0% test coverage (87% overall). It was exercised manually against real data, but it
  is the one module where a typo ships undetected.

## Phase 1 in one line

Hybrid recognition: on-device rectification → visual embedding match **and** targeted OCR in
parallel → fused calibrated confidence → auto-confirm or top-3 user pick. Two engines that fail on
different inputs, so the system knows when it is unsure.

## Next step

The sealed-product flip-edge (Phase 05's flip-side of the deal sniper, applied to query-keyed
sealed products) shipped 2026-08-19 (Phase 05c) — see
[design spec](docs/superpowers/specs/2026-08-19-sealed-product-ev-design.md) +
[plan](docs/superpowers/plans/2026-08-19-sealed-product-ev.md). The sealed purchase ledger +
profit tracker + Google Sheets sync (OAuth) shipped 2026-08-20 (Phase 05d) — a reseller leg
that logs buys, refreshes live profit from the 05c sold-comps median, and mirrors the ranked
ledger to a Google Sheet. Three candidates now, all honestly framed:

1. **Rip EV (expected pull value)** — the remaining Phase 05 leg. What is a sealed product worth to
   *rip open* vs. *flip sealed*? Needs **pull-rate data** we don't have yet (the per-set pull odds
   for the expected-value math) plus a `SealedProduct` master (the "product" is currently the
   user's free-text query). The sealed flip-edge provider + engine patterns make a rip-EV engine
   swappable in once the data lands.
2. **The full Grade predictor** (corner/edge/surface scoring + P(grade) + grading EV). The data
   infrastructure is unblocked (3b): rectified crops persist, grade-labels + self-annotation collect
   the only honest labelled dataset, and the graded-price provider + grading-upside spread are live.
   What remains is the corner/edge/surface scoring and the P(grade) model — which needs the labelled
   dataset to accrue from real mailed-in grades.
3. **Phase 6 — set-completion optimizer** (cheapest path to finishing a set). Unblocked by the
   catalog + pricing layer; no new external data dependency.

The deal sniper's natural follow-up — **deal alerts** (fire a 3c alert when a new listing clears
the rip/flip thresholds) plus **eBay sold-comps evidence** backing the raw market price — shipped in
Phase 05b (2026-08-04). The sealed flip-edge shipped 2026-08-19 (Phase 05c); the sealed purchase
ledger + profit tracker + Google Sheets sync shipped 2026-08-20 (Phase 05d); the remaining Phase 05
leg is rip EV (expected pull value), blocked on pull-rate data.

## Responsive UI overhaul — shipped 2026-08-20

A full visual + responsive overhaul of the frontend
([plan](docs/superpowers/plans/2026-08-20-responsive-ui-overhaul.md)), front-end-only (backend,
`data/`, and the 105-scan baseline untouched). **126 frontend tests stayed green throughout;
build clean.**

- **Responsive shell** — `useIsDesktop()` (matchMedia `min-width:1024px`, jsdom-safe → `false` in
  tests) decides between a desktop left **sidebar** nav (`<aside class="app-sidebar">`) and the
  mobile **bottom-nav**; exactly one is mounted at a time so `getByRole("button", { name: "Scan" })`
  still resolves to a single element. The sidebar reuses the existing `TabButton` + glyphs verbatim,
  so all 8 tab accessible names are byte-identical. Desktop: sidebar pinned left, content
  max-width 1180px centered with `clamp()` padding, sticky glass header; `1440px` widens to a
  264px sidebar + 1320px content. Mobile layout untouched.
- **Polished motion (Framer Motion 12)** — `<AnimatePresence mode="wait">` + `PageTransition`
  fade+slide on every tab switch and the CardDetail overlay; `WatchCardSheet` overlay fades and the
  sheet springs in (reduced-motion: opacity-only); list surfaces stagger their items on mount
  (`motion.ul` + `staggerContainer` → `motion.li` + `staggerItem`) with hover-lift / tap-scale.
  All motion is `useReducedMotion`-gated.
- **Refined dark-glass identity** — glass surfaces (backdrop-filter + hairline border + top-highlight
  gradient) layered on the existing card classes; primary CTAs get the yellow gradient fill + glow;
  RIP/flip chips and up/down pills get gradient treatments; inputs get glass insets + focus rings.
  All additive CSS — no class renamed, the flat `--surface` backgrounds remain as fallback.
- **Desktop multi-column grids** — deal/alert/browse lists lay out in 2–3 columns on desktop; the
  portfolio table widens; mobile stacked-card layout untouched.

**Do-not-break contract held** — every class name, `input[name]`, `aria-label`, button accessible
name, `data-label`, and honest-empty-state string the 126 tests query was preserved; motion wraps
existing elements (a `motion.button` still renders `<button>`), CSS is additive.

## Living UI — shipped 2026-08-20

A "Living UI" phase on top of the responsive overhaul, making the app feel alive and interactive
([plan](docs/superpowers/plans/2026-08-20-living-ui.md)). Frontend-only (backend, `data/`, 105-scan
baseline untouched). **146 frontend tests green (126 prior + 20 new); build clean.** Executed via
subagent-driven-development (fresh implementer per task, continuous execution).

- **Dashboard (Home) landing tab** — `Dashboard.tsx` is now the default landing surface (default
  view `alerts`→`home`). Reads `GET /collection/portfolio` once on mount; renders animated count-up
  KPIs (market value, cost basis, unrealized P/L, priced/unpriced), an allocation donut + movers
  bars (inline SVG, `viz.tsx`), and quick-action CTAs. Honest-empty when no holdings/fetch fails —
  never `$0`. New `useCountUp.ts` (rAF, reduced-motion-gated, jsdom-safe), `Reveal.tsx` (scroll-reveal),
  `useReducedMotionSafe.ts`. A 9th **Home** nav tab (first in both navs) with `HomeGlyph`.
  **Default-view safety:** BulkScan's fetch stub returns `200 {}` for `/collection`, so
  `getPortfolio()` resolves to `{}` (no throw); Dashboard null-guards `summary` + try/catches the
  fetch → `{}` renders the empty state, never crashes. CTA buttons use distinct verb-phrase names
  (`"Start scanning"`, `"Browse the catalog"`, …) — never an exact nav-tab name — so
  `getByRole("button", { name: "Scan" })` still resolves to one button.
- **Command palette + keyboard shortcuts** — `CommandPalette.tsx`: Cmd/Ctrl+K overlay (renders
  nothing when closed → no DOM collision); nav commands + debounced `searchCards` → opens card
  detail. AppShell keydown listener: Cmd/Ctrl+K toggles, `1`–`9` jump tabs, Escape closes — ignored
  when typing in an input/textarea/select/contenteditable. A `"Search"` (`⌘K`) header trigger.
- **Toast notifications** — `Toast.tsx`: `ToastProvider` + `useToast` + `ToastContext` whose
  **default is a noop**, so `useToast()` never throws without a provider. `<ToastProvider>` wired in
  `main.tsx` (production) only → **every existing test (no provider) fires zero toasts → zero
  collision.** Toasts render via `createPortal(..., document.body)` (pure-text, no action buttons)
  so `container.*`-scoped tests don't see them. Wired to App confirm/bulk-add-all, AppShell watch
  onCreated, SealedLedger log/refresh/sync.
- **Global polish** — additive CSS: animated gradient mesh `body::before`, Dashboard/palette/toast
  styles, `:focus-visible` rings, a once-on-mount view-transition shimmer. All new selectors.

**Do-not-break contract held** — 9 nav accessible names, every frozen class/input/aria/button/
empty-state string, and the one-element `getByRole("button",{name:"Scan"})` invariant preserved.
Default-view change safe by construction (null-guard + try/catch + distinct CTA names). Toast system
safe by construction (default-noop context → zero toasts in tests). 105-scan baseline 0 regressions.

## Grading Studio — shipped 2026-08-21

The honest form of the grade predictor. A learned predictor (corner/edge/surface scoring +
P(grade)) is impossible today — `grading_labels` = 0 and `graded_price_snapshots` = 0, so there is
nothing to learn from, and faking one would violate the honesty ethos. Instead of pretending to
predict, the Grading Studio is a **transparent calculator of the user's own inputs**: the one
measurable sub-grade (centering, from the scan) supplies a hard ceiling, and the user supplies the
other three (corners/edges/surface) as self-estimated sub-scores. The studio combines them into an
estimated grade band with a calibrated confidence and explicit caveats — never a verdict on the card.
Frontend-only; backend, `data/`, and the 105-scan baseline untouched. **165 frontend tests green
(146 prior + 19 new); build clean.**
([plan](docs/superpowers/plans/2026-08-21-grading-studio.md))

- **Pure calculator — `frontend/src/lib/gradeEstimate.ts`** — `estimateGrade(subs, centering,
  grader)`: estimate = `min(corners, edges, surface, centeringCap?)` snapped per grader (PSA → whole;
  CGC/BGS → half-points), clamped [1, 10]. `binding` = sub-scores at the min. `confidence` = high
  (centering measured+certain AND spread ≤0.5) / medium / low. `caveats` always state these are the
  user's estimates, not a prediction from the image, and that the overall is roughly the lowest
  sub-grade with grader discretion — not a guarantee. 9 unit tests.
- **Component — `frontend/src/components/GradingStudio.tsx`** — pure, no fetch, no motion. Three
  range inputs (1–10 step 0.5, defaults 9) with animated fill bars; estimated-grade readout with a
  confidence pill (`--ok`/`--warn`/`--down`); a "Centering ceiling" readout (PSA {cap} / too close to
  call / unmeasured); the binding line; a grader select (PSA/CGC/BGS) + "Reset estimates"; caveats
  list. 8 component tests.
- **Mount points** — `ScanResult.tsx` (card-gated, measured centering flows in from the scan) and
  `CardDetail.tsx` (sub-score-only, `centering={null}` for a card you own but haven't scanned). Both
  reuse the same pure component.
- **Styles — `frontend/src/styles.css`** — additive `.grading-studio*` block (glass card, studio-in
  keyframe, grade grid, confidence pills, sub-bar gradient, grader select, caveats). 3-column sub-score
  grid ≥880px. Reduced-motion disables animation/transitions. No existing rule renamed/removed.

**Do-not-break contract held** — the studio is pure (no fetch, no motion) with distinct
`.grading-studio*` classes + "Reset estimates" button, so it never collides with BulkScan's
`screen.*` queries or any frozen string. One pre-existing over-broad assertion in `centering.test.tsx`
(forbade the bare word "centering" anywhere in `ScanResult`) was relaxed to assert the
CenteringPanel's own verdict strings are absent — the `.centering` null check already enforces the
panel's absence (the test's true intent), and the studio legitimately discusses centering as one of
four sub-grades. 105-scan baseline 0 regressions.

## Set-completion optimizer — shipped 2026-08-22

A read-only set-completion optimizer: per-set owned/missing checklist with an honest estimated cost to
complete, resolved through the sacred `PriceService.latest_price` path. No new tables, no migrations,
no `data/` writes. **584 backend + 175 frontend tests green; build clean; 105-scan baseline untouched.**
([plan](docs/superpowers/plans/2026-08-21-set-completion.md))

- **Service — `backend/src/cardplatform/catalog/completion.py`** — `CompletionService` + four frozen
  dataclasses + a natural-sort key (plain numerics, then `4a`-style suffixes, then `TG01`-style prefixes).
  `list_sets` groups owned + checklist counts, filters with `func.lower().like()` (not `ilike`), orders
  by release_date desc, pct with no divide-by-zero. `set_detail` natural-sorts cards, prices only the
  missing ones via `latest_price(card.id, "normal")`, maps the `""` source-timestamp sentinel to `None`.
  Cost semantics are honest: `0.0` only when complete, `None` when all-missing-unpriced, sum otherwise;
  `unpriced_missing` always surfaced.
- **Routes — `backend/src/cardplatform/api.py`** — `GET /sets` (q optional, blank→422; limit 1–200) and
  `GET /sets/{set_id}` (unknown→404). Pydantic v2 wire models in `catalog/api_models.py`.
- **Frontend — 10th Sets tab (`Sets.tsx`) + `SetDetail.tsx` overlay** — searchable set list with
  progress bars; overlay with three KPIs (owned/total, pct, est. cost), an `unpriced: N card(s)` caveat,
  and a checklist grid (Owned badge / priced line with source + staleness / "no market price"). "Complete"
  renders instead of `formatMoney(0)` so no `$0.00` leaks; null cost renders `—`. AppShell wires the tab
  into both navs + the command palette with a `SetsGlyph`.
- **Styles — `frontend/src/styles.css`** — additive `.sets-*`, `.set-detail-*`, `.checklist-*` blocks +
  a visual-only `.bottom-nav { overflow-x: auto }` safety net for 10 tabs on narrow phones. No existing
  rule renamed/removed.

**Do-not-break contract held** — the 10th tab is named "Sets" (never "Scan"), so BulkScan's
`getByRole("button", { name: "Scan" })` still resolves to one element. All new classes are distinct; no
frozen string touched. **Sacred constraints held** — `latest_price` only; staleness surfaced;
`func.lower().like()`; honest 0% / `—` / "no market price"; read-only. 105-scan baseline 0 regressions.
