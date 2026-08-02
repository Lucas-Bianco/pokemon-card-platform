# AI_CONTEXT.md — bring any AI model up to speed on this project

> **Purpose:** this is the single file to hand an AI assistant so it understands what this project
> is, what has been built, what has been *measured*, and what not to break. Read it top to bottom
> before proposing anything.
>
> **Keep it current.** Update this file after any change that alters architecture, measured
> results, or the roadmap. A stale onboarding doc is worse than none, because it is trusted.
>
> Last updated: **2026-08-02**

---

## 1. What this is

A **local-first Pokémon trading-card recognition and valuation platform**. Point a phone camera at a
physical card; it identifies the card out of ~20,400 and tells you what it is worth.

Built as **one platform in phases**, not separate apps. Every module shares a card-recognition core,
a pricing layer, and a collection store.

Owner: Lucas. Public repo: https://github.com/Lucas-Bianco/pokemon-card-platform
Site: https://lucas-bianco.github.io/pokemon-card-platform/

**Design values that drive most decisions here:**
- **Never return a confidently wrong answer.** Declining to guess is strictly better than guessing
  wrong. This is why the pipeline has an `ambiguous` state and calibrated confidence.
- **Measure, don't assume.** Every significant claim in this file has a number behind it, produced
  by a script that can be re-run.
- **Local-first.** All inference runs on the owner's machine. Only catalog and price data sync.

---

## 2. Current state (2026-08-02)

| Phase | What | Status |
|---|---|---|
| 0 | Foundation: catalog, pricing, collection store | ✅ Complete |
| 1a | Recognition engine: rectify → embed → OCR → fuse | ✅ Complete |
| 1b | Scan PWA: camera, candidate picker, scan logging | ✅ Complete |
| 1c | Robust detection: multi-strategy chain | ✅ Complete |
| 2 | Portfolio tracker: cost basis, P/L, charts | ✅ Complete — ships correct, becomes useful as data accrues (§6) |
| 3 | Grade predictor: CV grading + grading EV | In progress — data infrastructure shipped (§10); full predictor still planned |
| 3b | Grading data infrastructure: rectified-crop persistence, grade-label schema + self-annotation, graded-price provider, grading-upside spread | ✅ Complete |
| 3c | Watchlist + restock/price/drop/auction alerts (CollectorVault-style 5-tab UI) | ✅ Complete (§11) |
| 4 | Bulk cataloger: many cards per photo | Planned |
| 5 | Deal sniper + sealed EV | Planned |
| 6 | Set-completion optimizer | Planned |
| 7 | Counterfeit detector | Planned |

**Tests:** 443 backend (pytest) + 90 frontend (vitest).

### UI — "Grading Lab" (2026-08-01)

Both public surfaces share one Grading Lab design language (dark `#0b0d12`, restrained Pokémon-yellow
`#ffcb05` accents, Inter + JetBrains Mono, premium motion).

- **Marketing site** is now a **Next.js 15 static-export app in `site/`** (App Router, `output:'export'`,
  `basePath:'/pokemon-card-platform'`, `images.unoptimized`), built and copied into `docs/` for GitHub
  Pages (which serves `docs/`; no CI workflow). Scroll-scrubbed 3D hero card flip (GSAP + CSS 3D, **no
  WebGL**), scroll-scrubbed pipeline assembly, interactive roadmap with count-ups, stack + footer.
  `prefers-reduced-motion` respected; all content renders with JS off. `docs/superpowers/` (specs +
  plans) is preserved across every deploy — the footer links to it raw. Source of truth for site copy +
  roadmap rows: `site/app/sections/data.ts`.
- **Scanner** stayed on Vite + React 19 + basic-ssl + PWA (no stack migration) but was redesigned
  mobile-first: `CameraCapture` now **captures only the guide-box region** (cover-crop fix — what you
  align is what gets sent) with a metadata ready-gate + capture flash; `CornerAdjust` has 44px handles
  with robust pointer logic; `PortfolioView` is responsive (table on desktop, stacked cards on mobile,
  `.portfolio-table` class + asserted text preserved); global CSS breakpoints, safe-area insets, 44px
  touch targets, app chrome + bottom nav; real PWA 192/512/maskable icons + apple meta + enriched
  manifest. Honest empty states unchanged. New: `frontend/src/lib/cameraCrop.ts` (pure guide-crop
  math, tested), `frontend/scripts/gen-icons.py`.

### Measured recognition performance — on real phone photos of physical cards

This is the number that matters. Everything before Phase 1b was measured on *degraded reference
images*, which flattered it badly.

| | value |
|---|---|
| **Precision when the pipeline commits** | **100%** (29/29, zero confident errors) |
| **Coverage** (scans producing a confident answer) | **65%** (was 31% before Phase 1c) |
| True card at rank 1 | **88%** |
| True card in top 3 | **98%** |

**Do not quote a blended "accuracy" figure.** An earlier metric reported 74.4% by counting a
*declined* `ambiguous` result as a *wrong answer* — conflating refusing to guess with guessing
wrong, which are opposites here. Always report precision and coverage separately.

---

## 3. Architecture

```
camera photo
   ↓
detect_candidates()        several strategies each propose a card-shaped quad
   ↓
rectify_from_corners()     perspective-warp each proposal to a flat 600×825
   ↓
CardEncoder.embed()        CLIP ViT-B-32 → normalized 512-d vector   (2.2 ms each)
   ↓
CardIndex.search()         FAISS exact inner-product over 20,391 cards (0.01 ms)
   ↓                       ← the best-matching proposal wins here
CollectorNumberReader()    targeted OCR of the collector number, ONCE on the winner (~1 s)
   ↓
fuse()                     visual + OCR → confident | ambiguous | not_found
```

### Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI | The CV/ML ecosystem is Python-first |
| DB | SQLite via SQLAlchemy ORM | Single-user local-first; no SQLite-specific SQL so Postgres stays cheap |
| Encoder | open-clip ViT-B-32 `laion2b_s34b_b79k` | 2.2 ms/card, 512-d, 40 MB index |
| Vector search | FAISS `IndexFlatIP` | Exact search; 20k vectors is tiny, no approximation needed |
| OCR | rapidocr-onnxruntime | Works on Windows/3.12; ONNX suits a future on-device path |
| Detection | OpenCV | Canny + Otsu/minAreaRect strategies |
| Frontend | React 19 + TypeScript + Vite 8, PWA | One codebase, phone + desktop |

### Layout

```
backend/src/cardplatform/
  config.py          Settings (env prefix CARDPLATFORM_)
  db/                models.py, session.py, migrations.py (idempotent nullable-ALTER helper, no Alembic)
  catalog/           dump.py (GitHub JSON), loader.py (idempotent upsert)
  prices/            provider.py (protocol), pokemontcg.py, service.py — latest_price + price_history;
                     graded_provider.py + pkmnprices.py + graded_service.py — graded sold comps
                     (degrades to [] without CARDPLATFORM_GRADED_PRICE_API_KEY, never raises);
                     listings_provider.py (Protocol + ListingQuote) + ebay_listings.py
                     (EbayListingsProvider — mirrors PkmnPricesProvider, degrades to []) +
                     listings_service.py (ListingsService — immutable ListingSnapshot dedupe,
                     lowest_price None-not-0.0, previous_listing_ids by fetched_at-grouping)
  alerts/            engine.py (AlertEngine — 5 alert types, per-watch SAVEPOINT isolation,
                     never-raises), notify.py (NotificationService — in-app/push/email, degrades
                     gracefully per channel), api_models.py (Pydantic wire models)
  collection/        store.py — add/remove/list/valuation + portfolio/summary/set_cost_basis
  recognition/       detectors.py, rectify.py, encoder.py, index.py, ocr.py, fusion.py, service.py
                     (persists the rectified crop to data/rectified/ + stamps scan_logs.variant)
  grading/           store.py (GradingLabelStore — self-annotation), upside.py (GradingUpsideService —
                     the raw/PSA-9/PSA-10 spread, honest nulls, never a prediction)
  scans/             store.py — logs every scan as ground truth (rectified_path + variant columns)
  api.py             FastAPI, cli.py  CLI
backend/scripts/     evaluate_recognition.py, evaluate_detection.py, spot_check.py
frontend/src/        api/, lib/ (format, cameraCrop), components/  (CameraCapture, ScanResult,
                     CandidatePicker, PriceLine, CornerAdjust, PortfolioView, PriceChart,
                     GradingUpside — the spread panel; ScanResult hosts the self-annotation form;
                     AppShell — 5-tab nav Scan/Vault/Alerts/Browse/More, Alerts-first; CardDetail,
                     Browse, AlertsFeed, WatchCardSheet, More — the Phase 3c alert/watchlist UI)
frontend/public/     manifest.webmanifest, icon-192/512/icon-maskable-512.png, icon-source.svg
frontend/scripts/    gen-icons.py (rasterize icon-source.svg → PNGs)
site/                Next.js 15 marketing app — app/sections/ (Hero, Problem, Pipeline, Roadmap,
                     Grading, Stack, Footer), app/sections/data.ts (copy + roadmap rows), providers.tsx
                     (Lenis + GSAP ScrollTrigger), next.config.mjs (static export + basePath)
api.py Phase 2 endpoints: GET /collection/portfolio (items + summary in one round trip,
                     all valuation server-side via latest_price), PATCH /collection/{id}
                     (cost basis / acquired_at / condition / notes), DELETE /collection
                     (?card_id=&variant=&quantity=), GET /cards/{id}/prices/history
                     (?variant=&days=). Each history point carries its own source +
                     source_updated_at — never blend sources into one canonical number.
api.py Phase 3b endpoints: POST /scans/{id}/grade-label + GET /scans/{id}/grade-label +
                     GET /grading/labels (self-annotation), GET /cards/{id}/grading-upside
                     (?variant=) — the spread {raw_price, psa9, psa10, grading_fee,
                     upside_to_10 | null, graded_prices_unavailable}. CLI: refresh-graded-prices.
api.py Phase 3c endpoints: GET/POST/PATCH/DELETE /watchlist (422 validation per alert_type),
                     GET/PATCH /alerts + POST /alerts/read-all + GET /alerts/unread-count,
                     GET /cards/{card_id}/listings?variant= (honest listings_unavailable flag),
                     GET /push/vapid-public, POST/DELETE /push/subscribe. A startup poll loop
                     runs AlertEngine.check_alerts() every alert_poll_min minutes (skips if <=0).
                     CLI: check-alerts (one-shot), gen-vapid (VAPID keypair for web push).
data/                GITIGNORED — 20,391 card images, 40 MB FAISS index, SQLite db, 105 real scans
```

---

## 4. Hard-won gotchas — these all cost real time to discover

**Environment**
- **Python 3.12 only.** System Python is 3.14 and lacks the ML wheels. Always `backend/.venv`.
- **Install torch and torchvision together from the cu128 index, and re-run that install after
  anything that depends on torch.** `pip install open-clip-torch` silently replaces the CUDA build
  with a CPU one; repairing torch alone then breaks torchvision with
  `operator torchvision::nms does not exist`.

**Data**
- **Decode downloaded JSON explicitly as UTF-8.** ~430 card names are accented.
- **Never derive a cache filename from an image URL.** 661 catalog images have no file extension,
  and two real card ids (`ex10-!`, `ex10-?`) contain characters illegal in NTFS filenames. Key on
  `card_id` and percent-encode.
- **Use `func.lower(col).like(...)`, not `ilike`.** SQLite's `LIKE` is case-insensitive for ASCII
  only, so `ilike` misses accented names.

**Pricing**
- **Never resolve "the latest price" ad hoc.** Call `PriceService.latest_price(card_id, variant)`.
  tcgplayer prices per variant (`holofoil`, `normal`, …) while cardmarket publishes one
  `"aggregate"` row per card, so a naive variant-filtered query silently values cardmarket-only
  cards at $0.
- **Always surface staleness.** Return `source` and `source_updated_at`. Real example: cardmarket
  said $1531 while tcgplayer said $800 for the same card on the same day. Never blend sources.
- **Snapshots are immutable.** Insert; never update.
- **The price API fails ~83% of requests.** Retries with backoff are mandatory. An on-demand fetch
  measured 4.3 s mean, 27 s worst — never block a scan on it.

**Recognition**
- **Never count "found a card-shaped quad" as "found the card".** Adaptive thresholding once scored
  56/56 purely by returning the whole image border, whose aspect ratio passes the shape gate on a
  portrait photo. Verify a detector by running recognition on its output.
- **`approxPolyDP` demanding exactly 4 vertices is what broke detection originally.** Real photos
  have rounded corners and noise, so it lands on 5–7 vertices and discards a visible card. Fitting a
  rotated rectangle is the robust primitive.
- **A single "better" detector was measured NOT strictly better.** `otsu_rect` alone recovered 33
  failures but regressed 6 working scans. The chain regresses none.
- **Only a full `N/M` OCR reading may override the visual winner.** A bare number may confirm it,
  never promote a different candidate — a real misread (`1/102` → bare `102`) would otherwise turn a
  correct answer into a confident wrong one.

**Frontend**
- **The camera requires HTTPS.** `getUserMedia` is *absent* over plain HTTP — not a prompt, a hard
  refusal. The dev server uses a self-signed cert.
- **An HTTPS page cannot call the HTTP backend.** That is mixed content and no CORS header fixes it.
  All requests go through Vite's `/api` proxy.

---

## 5. How to run things

```bash
# install (backend)
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\backend[dev,ml]"

# tests
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest        # from repo root
npm --prefix C:\ClaudeKnowledge\frontend test

# run the app — needs BOTH, in separate terminals
C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --host 0.0.0.0 --port 8000
npm --prefix C:\ClaudeKnowledge\frontend run dev        # https://<lan-ip>:5173

# data maintenance
cardplatform.exe sync-catalog                  # idempotent, resumable
cardplatform.exe build-index                   # downloads ~20k images; re-runs skip cached
cardplatform.exe refresh-collection-prices     # run on a schedule so price history accrues
cardplatform.exe check-alerts                  # one-shot: run AlertEngine over active watches
cardplatform.exe gen-vapid                      # print VAPID public/private key env lines for web push

# evaluation — score any recognition/detection change against the 101 real scans
python backend/scripts/evaluate_detection.py   # fails the run on a single regression
python backend/scripts/evaluate_recognition.py --sample 500
```

---

## 6. What is blocked, and on what

**Phase 2 (portfolio tracker) shipped 2026-08-01 — code correct now, useful as data accrues.** The
ship decision is the same "never fake missing data" value the rest of the app follows: a chart with
one snapshot renders a single dot and says "need more history to draw a trend"; P/L with no cost
basis renders an em dash, never `+$0.00` and never market value dressed up as profit. Measured
2026-08-01, the data has not yet accrued:
- 0 of 37 collection items have a cost basis → every holding shows an em dash for unrealised P/L
- 0 price series have more than one distinct `source_updated_at` → every chart is the single-dot state

Both causes are unblocked in code — the scan flow asks "what you paid" (optional), `PATCH
/collection/{id}` backfills cost basis on existing holdings, and `refresh-collection-prices` accrues
history. **The honest empty/single states are the feature, not a workaround.** Re-measure both counts
after a few weeks of scheduled refresh runs; the UI turns the em dashes and single dots into real
trends on its own as data lands.

---

## 7. The most useful next levers

1. **Fix centering's coverage on real photos — it is built but only 4% usable.** See §9.
2. **Phase 3 full grading** (corners, edges, surface, P(grade)) — the data infrastructure is now
   unblocked (§10: rectified crops persist, grade-labels + self-annotation collect the only honest
   labelled dataset, graded-price provider + grading-upside spread are live). What remains is the
   corner/edge/surface scoring + the P(grade) model, which needs the labelled dataset to grow.
3. **A different OCR engine**, if OCR is revisited. See the dead ends below: cropping and
   preprocessing are exhausted, so the remaining gain would have to come from the recogniser itself
   (PaddleOCR, or Tesseract with a digit whitelist) or from higher-resolution capture.

### OCR dead ends — measured and disproved, do not repeat

Two plausible-sounding theories were tested against the real scans and **both were wrong**:

- **"The quad is misaligned, cutting off the bottom of the card."** Disproved. Detected quads
  measured a median aspect of 1.396 where OCR succeeded and **1.381 where it failed** — both
  essentially a real card's 1.400. Zero failing quads were shorter than 1.35. Padding the quad
  downward made things *worse* (4 → 2 recovered). This theory was briefly recorded here as the top
  lever; it is not.
- **"The number is too small a target inside a wide strip."** Disproved. Tight bottom-left and
  bottom-right corner crops at 8× upscale scored 24 correct / 7 wrong against the shipped 27 / 4,
  and as a *fallback* recovered nothing the existing path missed.

Visual inspection settled it: the number is present, correctly positioned, and legible to a human —
rapidocr simply misreads small blurry digits (`035/159` → `95`, `116/159` → `716`). That is a limit
of the recogniser and the source photo, not of the crop.

### OCR work done 2026-07-31

Diagnosed all 15 OCR failures across 39 real crops before changing anything:

| cause | count |
|---|---|
| OCR saw text the parser rejected | 8 |
| read a wrong number | 3 |
| number outside the bottom strip | 2 |
| no text at all | 2 |
| **card rectified upside down** | **0** — hypothesis disproved |

Two fixes shipped, both measured:
- **Suffix letters in the token pattern.** Real ids use them (`63a`, `12b`). OCR had read `63a/111`
  correctly and the parser threw it away because it only allowed letters as a *prefix*.
- **A wider fallback band, accepting only a full `N/M` reading.** The wide band also contains rules
  text and copyright lines, so a bare number found there is usually not the collector number.

Then a third fix, from a signal that had been discarded entirely:
- **Gate on rapidocr's confidence score at 0.85.** It returns one per read and nothing was using it.

Cumulative over the 39 crops: **24 → 28 correct, 4 → 0 wrong.** Strictly better on both axes. The
gate *gains* a read rather than only suppressing bad ones, because discarding a low-confidence
misread lets the wide-band fallback run and find the real number underneath it. The extra silences
are the safe outcome — with no OCR the visual match decides alone, and that is rank-1 correct 88% of
the time.

Rejected after measurement: an `S`→`5` confusion repair (+2 wrong, +0 correct); allowing bare
numbers in the wide band (4 → 8 wrong); and multi-scale voting across 3/4/6× (no gain).

End-to-end: **63% → 65% coverage, 0 regressions.** The lift is smaller than the read-count gain
because OCR only arbitrates when its reading uniquely matches one shortlisted candidate.

`_MIN_OCR_CONFIDENCE` is calibrated on 39 samples — re-check with `evaluate_detection.py` if the OCR
engine or preprocessing changes.

*Done 2026-07-30: the PWA now has a collection view. It shows holdings and a valuation summary, and
renders unrealised P/L as an em dash when no cost basis exists rather than reporting market value as
pure profit.*

*Done 2026-08-01: Phase 2 portfolio tracker shipped. `PortfolioView` supersedes that collection view
— per-item market price and unrealised P/L, allocation by set, top movers, cost-basis editing and
removal, and a hand-rolled SVG `PriceChart` (no chart library) that renders a single dot as "need
more history" rather than faking a trend. All valuation stays server-side via `latest_price`; the
client never resolves "the latest price" itself. Code is correct now and turns honest empty states
into real charts as cost basis and price history accrue.*

---

## 8. Working agreements

- **Score every recognition or detection change with `backend/scripts/evaluate_detection.py`.** It
  replays the real scans and fails on a single regression. A confidently wrong card is worse than a
  missed detection.
- **Ask before destructive commands.** In particular, never delete anything under `data/` — it holds
  20,391 downloaded images, a 40 MB index, the database, and 101 irreplaceable real scan photos.
- Match the style of surrounding code.
- `CLAUDE.md` holds the same conventions in condensed form for Claude Code specifically.

---

## 9. Phase 3a — centering: built, correct, and mostly unusable on real photos

Shipped 2026-07-31 on branch `phase-3a-centering`. **248 backend + 29 frontend tests.**

Centering is the one PSA sub-grade measurable without training data — a distance, not a judgement.
Corners, edges, surface and grading EV stay blocked: they need labelled graded cards and
graded-card prices, and this project has neither.

### What is proven correct

- Synthetic cards with centering exact by construction measure **0.00% error**, at every border
  thickness from 6px to 60px. Mirror-equivariance holds on real renders.
- An earlier "2.6% systematic bias" was **disproved**: the skew was small-sample noise (it inverts at
  n=79), and worst-axis is a `max()` over four shares so it is ≥50 by construction and can never
  average to 50 under any noise. A matched null model predicts 51.28% against an observed 52.27%.
- Output is always a **ceiling** — "centering allows up to PSA 9" — never a grade, with front-only
  and one-of-four caveats in the UI, and a `psa_cap_range` when the interval straddles a band.

### The blocking problem

Run over all 101 real scans (`backend/scripts/evaluate_centering.py`):

| outcome | count | share |
|---|---|---|
| measured | 4 | **4%** |
| declined: no card detected | 3 | 3% |
| **declined: border unmeasurable** | **94** | **93%** |

**Diagnosed cause — do not re-diagnose this.** It is *not* that photos are too noisy overall: peak
border purity across 98 real crops has a **median of 0.92**, and 55% clear the 0.90 threshold. The
guard rejects because it requires **both sides of an axis to be clean simultaneously**, and a real
photo with directional lighting almost always has one shadowed edge.

This is the same failure class as the earlier detector work: **a threshold calibrated on the wrong
population.** `MIN_BORDER_PURITY` was tuned against clean catalog renders, then applied to phone
photos.

Plausible fixes, none yet tested:
- Judge purity **per axis** rather than globally — report the horizontal ratio when only the left/right
  borders are clean, and say the vertical is unmeasured.
- Normalise illumination across the crop before classifying the border.
- Lower the threshold for photos while keeping it high for renders — but note that the guard exists to
  reject modern textured frames, so loosening it naively brings that failure back.

**The feature is correct but not yet earning its place.** Fixing coverage is the next lever, and the
101 saved scans are the test set to fix it against.

---

## 10. Phase 3b — grading data infrastructure (unblocks the Grade Predictor)

Shipped 2026-08-01 on branch `phase-3b-grading-infra`. **374 backend + 65 frontend tests.** The full
Grade predictor (corner/edge/surface scoring + P(grade)) is still blocked on *labelled* graded-card
data — this phase ships the infrastructure to collect it and the graded-price leg, so the predictor is
buildable as soon as Lucas's own annotated cards accrue. 105 real scans preserved throughout; the raw
`PriceSnapshot` table and recognition behavior are untouched.

**Why a spread, not a prediction.** P(grade) needs the labelled dataset we don't have. Shipping a
single "expected value" number would be confidently-wrong. So `GET /cards/{id}/grading-upside` returns
the *upside spread*: raw latest price, PSA-9 and PSA-10 sold comps, the grading fee, and
`upside_to_10 = psa10.market − raw.market − fee` (null unless both inputs present). Missing graded
prices → null fields + `graded_prices_unavailable: true` (never a fake `$0`, never a fake EV).

What shipped (TDD, subagent-driven, two-stage review per task):
- **T1 — schema + migration helper.** `db/migrations.py` `run_migrations(engine)`: idempotent
  `PRAGMA table_info` → nullable `ALTER TABLE ADD COLUMN`, called after `Base.metadata.create_all()`
  (no Alembic). Validates table names loudly; narrows excepts to `OperationalError`. New tables
  `grading_labels` (unique scan_id, grade Float for half-grades, grader, cert?, notes?) and
  `graded_price_snapshots` (mirrors PriceSnapshot + grade Float + grader, separate from the sacred
  raw table, dedupe on `(card_id, grader, grade, variant, source_updated_at)`). New nullable
  `scan_logs.rectified_path` + `scan_logs.variant`.
- **T2 — persist the rectified crop.** `recognition/service.py` writes the 600×825 rectified PNG to
  `data/rectified/<uuid>.png` and stamps `rectified_path` + `variant` on the scan log (fail-soft).
  This is the normalized input a future corner/edge/surface grader consumes.
- **T3 — grading-label store + API.** `grading/store.py` `GradingLabelStore`: `label(scan_id, …)`
  resolves card_id/variant from the scan (never the body), validates grade 1–10 and grader in
  {PSA,CGC,BGS}, upserts on unique scan_id. Endpoints `POST/GET /scans/{id}/grade-label`,
  `GET /grading/labels`. The only honest labelled dataset is Lucas's own cards — the self-annotation
  UI (T6) seeds it.
- **T4 — graded-price provider + service.** `prices/graded_provider.py` (Protocol) +
  `pkmnprices.py` `PkmnPricesProvider` (httpx + tenacity, env-keyed
  `CARDPLATFORM_GRADED_PRICE_API_KEY`; **degrades to `[]` on no key / 404 / transport / parse — never
  raises**) + `graded_service.py` `GradedPriceService` (immutable dedupe, `latest_graded`). CLI
  `refresh-graded-prices`. **Documented follow-ups** (not solved): PkmnPrices↔`base1-4` card-id
  mapping (adapter returns `[]` on mismatch); pagination (first page only).
- **T5 — grading-upside endpoint.** `grading/upside.py` `GradingUpsideService` → the spread above;
  uses only `PriceService.latest_price` + `GradedPriceService.latest_graded` (no ad-hoc resolution).
- **T6 — frontend.** `GradingUpside.tsx` (the spread panel, honest empty states mirroring
  PortfolioView: `—` + "no market price", graded-unavailable → the API-key hint, never `$0.00`) +
  `ScanResult.tsx` self-annotation form (grader/grade 1–10 half-steps/cert/notes → POST grade-label;
  fetches an existing label read-only). App threads `scanId`. Mobile-safe CSS.
- **T7 — site.** New scroll-animated `Grading` section: Centering lights up, Corners/Edges/Surface
  stay dimmed with "Needs labelled data" tags (never light up — no pretending), plus a scroll-driven
  upside-spread visual labelled "example" with the honest "spread, not a prediction" caption. Roadmap
  row 03b (done) + 03 set to in-progress. Rebuilt → `docs/` (superpowers/ preserved).

**Sacred constraints held:** no ad-hoc price resolution (only `latest_price`/`latest_graded`);
snapshots immutable; staleness surfaced; honest empty states unchanged on the scanner; no `data/`
contents deleted (only additions under `data/rectified/`); `func.lower(...).like` for text search.

---

## 11. Phase 3c — watchlist + restock/price/drop/auction alerts

Shipped 2026-08-02 on `main` (12 commits ahead of `origin/main` before push). **443 backend + 90
frontend tests.** A CollectorVault-inspired 5-tab app shell (Scan/Vault/Alerts/Browse/More,
Alerts-first default) over a new watchlist + notification engine. The same "never fake missing data"
value runs through it: the alert feed never invents events, listings degrade honestly when no source
key is set, and channels degrade silently when unconfigured. 105 real scans preserved; raw
`PriceSnapshot`, `GradedPriceSnapshot`, and recognition behavior untouched.

**Alert types (5), all idempotent.** `restock` (prev ids empty → curr non-empty), `new_listing`
(curr − prev non-empty), `price_target` (lowest listing ≤ target, cooldown via `alert_cooldown_min`,
re-arms when price climbs back above target), `auction_ending` (per-listing dedupe by `listing_id` in
`AlertEvent.context`), `drop_time` (fires a lead reminder then the drop, then stops). Idempotency for
restock/new_listing keys off **`Watch.last_seen_listing_ids`** (a per-watch JSON baseline), not
`ListingsService.previous_listing_ids` — because immutable snapshots with no fetch-record table make
empty fetches invisible (they insert no rows), so the per-watch baseline is the only correct diff
source. First poll (baseline `None`) fires nothing.

**Channels — `NotificationService.dispatch` never raises, each channel degrades independently:**
- **In-app** — always on; sets `delivered_inapp` defensively (the feed reads `AlertEvent` rows).
- **Web push** — `pywebpush` + VAPID (`CARDPLATFORM_VAPID_*`); gates on *both* public + private keys;
  prunes subscriptions on 404/410; success flag set on ≥1 delivery. Payload build wrapped in try/except
  so a push failure can't poison email.
- **Email** — `smtplib`, synchronous (testable), `timeout=10` (a missing timeout would block the poll
  tick forever), SMTP_SSL for 465 / SMTP+starttls for 587 / plaintext 25. `CARDPLATFORM_SMTP_*`.

**Never-raise engine.** `AlertEngine.check_alerts()` wraps each watch in `with session.begin_nested():`
(a SAVEPOINT) so a flush `IntegrityError` is isolated to that watch; per-watch try/except logs +
continues; the final commit is wrapped in try/except. A poisoned-session regression
(`test_flush_failure_does_not_poison_tick`) guards it. `_now()` is injectable for deterministic tests.

What shipped (TDD, subagent-driven; reviews ran inline T5–T8 after a backend usage-limit killed the
T5 spec-review subagent):
- **T1 — schema.** 4 new tables in `db/models.py`: `watchlist` (unique on
  `(card_id,variant,alert_type,target_price,drop_at)`, `last_seen_listing_ids` JSON baseline,
  `last_fired_at`, `active` default True), `listing_snapshots` (immutable, unique on
  `(card_id,variant,source,listing_id,source_updated_at)` with `""` sentinel for a missing source
  timestamp — NULLs are distinct under SQLite so the unique constraint would otherwise allow dups),
  `alert_events` (unread index on `(read_at,created_at)`, per-channel delivery flags),
  `push_subscriptions` (endpoint unique).
- **T2 — listings provider + service.** `prices/listings_provider.py` (`ListingQuote` frozen
  dataclass + `ListingsProvider` Protocol) + `ebay_listings.py` `EbayListingsProvider` (mirrors
  `PkmnPricesProvider`: tenacity retry, terminal-one-attempt on 404/401/bad-JSON, `RetryError`→`[]`,
  parse failure→`[]`, never raises; `source="ebay"`, documented keyword-search + auth caveats) +
  `listings_service.py` `ListingsService` (immutable dedupe, `lowest_price` returns None not 0.0,
  `previous_listing_ids` by `fetched_at`-grouping with `id.desc()` tiebreak).
- **T3 — engine.** `alerts/engine.py` `AlertEngine` — the 5 idempotent alert types above, SAVEPOINT
  isolation, injectable clock. Drop-time formula uses `last_fired_at < drop_at` (the contract's
  `… − lead` was a typo that would have blocked the drop fire — caught in review, fixed to match the
  prose/tests).
- **T4 — notifier + config + CLI.** `alerts/notify.py` `NotificationService` (the three channels
  above, no commit inside `dispatch` — the engine commits). `config.py` +10 fields (vapid_*,
  smtp_*, `alert_poll_min`=15, `alert_cooldown_min`=60). `pyproject.toml` adds `pywebpush>=2.0`.
  CLI `gen-vapid` (EC P-256 keypair via `py_vapid`, base64url public point + private scalar).
- **T5 — API + poll loop.** `alerts/api_models.py` (Pydantic v2, `from_attributes=True`, nullables
  surface as None) + 12 endpoints in `api.py` (additive +283/−3). A startup `@app.on_event("startup")`
  task runs `check_alerts()` every `alert_poll_min*60` (swallows per-tick exceptions, skips if ≤0;
  shutdown cancels). CLI `check-alerts` for a one-shot run. *Honest:* `GET /cards/{id}/listings`
  returns `listings_unavailable: settings.listings_api_key is None`; `GET /push/vapid-public` returns
  `""` when unconfigured.
- **T6 — app shell + card detail + browse.** `App.tsx` rewired to `<AppShell/>`; 5-tab bottom nav,
  Alerts-first default, slim header, unread badge; `CardDetail` reuses `GradingUpside` +
  `PriceChart`/`PriceLine` with honest listing empty states; `Browse` debounced `GET /cards?name=`.
- **T7 — alerts feed + watch sheet + more.** `AlertsFeed` (type-filter chips, relative time, unread
  accent, tap=mark-read+deep-link, honest radar-copy empty state, never fabricates events),
  `WatchCardSheet` (bottom sheet, 5 radio-type chips, conditional fields, client-side validation
  mirroring the 422 rules, `expectJsonOrDetail` surfaces backend 422), `More` (honest channel cards:
  push queryable via `getVapidPublic`, email/listings static "set `CARDPLATFORM_*`" hints, watchlist
  management toggles). Scan onboarding nudge (localStorage-gated, non-blocking, only for a recognized
  card with a market price).
- **T8 — site.** `site/app/sections/data.ts` Phase 05 → in-progress ("Watchlist + restock/price/drop/
  auction alerts shipped — rip-vs-flip modelling still planned"); new scroll-animated `Alerts.tsx`
  section (GSAP scrub + Framer reveal, 5 alert chips 📦✨🎯⏳⏰, `prefers-reduced-motion` static fallback,
  CSS defaults visible JS-off, honest "alerts fire only while a check runs" caption). Rebuilt →
  `docs/` (`.nojekyll` + `docs/superpowers/` preserved).

**Documented follow-ups (not solved):** the `@app.on_event` poll loop is deprecated-cosmetic
(lifespan handler is the clean replacement); eBay listings need a real keyword-search + auth adapter
(the provider degrades to `[]` until then, so restock/new_listing/auction alerts need
`CARDPLATFORM_LISTINGS_API_KEY` to fire); `previous_listing_ids` can merge two same-clock-tick fetches
(acceptable at a 15-min poll cadence); numeric `listing_id` assumed for the auction dedupe `LIKE`.

**Sacred constraints held:** no ad-hoc price resolution; snapshots immutable (listings too);
staleness surfaced; honest empty states (no `$0`, never fabricate events, channels degrade silently);
no `data/` contents deleted; `func.lower(...).like` for text search; `UtcDateTime` for tz-aware
columns; `""` sentinel for unique-constraint columns that may lack a source timestamp.
