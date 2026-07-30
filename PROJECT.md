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
| 1c | Robust card detection — the measured bottleneck | Next |
| 2 | Portfolio tracker — cost basis, P/L, price charts | Planned |
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
