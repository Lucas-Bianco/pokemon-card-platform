# Project: Technology + Trading Cards (Pokémon)

**Owner:** Lucas
**Started:** 2026-07-28
**Status:** Phase 0+1 design approved — see
[design spec](docs/superpowers/specs/2026-07-28-card-recognition-platform-design.md).
Next: implementation plan.

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
| 3 | Grade Predictor — CV centering/corner scoring + grading EV | Planned |
| 4 | Bulk cataloger — detect every card in one photo | Planned |
| 5 | Deal sniper + sealed EV — listings vs. sold comps, rip-vs-flip | Planned |
| 6 | Set-completion optimizer — cheapest path to finish a set | Planned |
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

Write the Phase 0+1 implementation plan.
