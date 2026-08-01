# AI_CONTEXT.md — bring any AI model up to speed on this project

> **Purpose:** this is the single file to hand an AI assistant so it understands what this project
> is, what has been built, what has been *measured*, and what not to break. Read it top to bottom
> before proposing anything.
>
> **Keep it current.** Update this file after any change that alters architecture, measured
> results, or the roadmap. A stale onboarding doc is worse than none, because it is trusted.
>
> Last updated: **2026-08-01**

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

## 2. Current state (2026-07-30)

| Phase | What | Status |
|---|---|---|
| 0 | Foundation: catalog, pricing, collection store | ✅ Complete |
| 1a | Recognition engine: rectify → embed → OCR → fuse | ✅ Complete |
| 1b | Scan PWA: camera, candidate picker, scan logging | ✅ Complete |
| 1c | Robust detection: multi-strategy chain | ✅ Complete |
| 2 | Portfolio tracker: cost basis, P/L, charts | ✅ Complete — ships correct, becomes useful as data accrues (§6) |
| 3 | Grade predictor: CV grading + grading EV | Planned |
| 4 | Bulk cataloger: many cards per photo | Planned |
| 5 | Deal sniper + sealed EV | Planned |
| 6 | Set-completion optimizer | Planned |
| 7 | Counterfeit detector | Planned |

**Tests:** 276 backend (pytest) + 52 frontend (vitest).

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
  db/                models.py, session.py
  catalog/           dump.py (GitHub JSON), loader.py (idempotent upsert)
  prices/            provider.py (protocol), pokemontcg.py, service.py — latest_price + price_history
  collection/        store.py — add/remove/list/valuation + portfolio/summary/set_cost_basis
  recognition/       detectors.py, rectify.py, encoder.py, index.py, ocr.py, fusion.py, service.py
  scans/             store.py — logs every scan as ground truth
  api.py             FastAPI, cli.py  CLI
backend/scripts/     evaluate_recognition.py, evaluate_detection.py, spot_check.py
frontend/src/        api/, lib/ (format, cameraCrop), components/  (CameraCapture, ScanResult,
                     CandidatePicker, PriceLine, CornerAdjust, PortfolioView, PriceChart)
frontend/public/     manifest.webmanifest, icon-192/512/icon-maskable-512.png, icon-source.svg
frontend/scripts/    gen-icons.py (rasterize icon-source.svg → PNGs)
site/                Next.js 15 marketing app — app/sections/ (Hero, Problem, Pipeline, Roadmap,
                     Stack, Footer), app/sections/data.ts (copy + roadmap rows), providers.tsx
                     (Lenis + GSAP ScrollTrigger), next.config.mjs (static export + basePath)
api.py Phase 2 endpoints: GET /collection/portfolio (items + summary in one round trip,
                     all valuation server-side via latest_price), PATCH /collection/{id}
                     (cost basis / acquired_at / condition / notes), DELETE /collection
                     (?card_id=&variant=&quantity=), GET /cards/{id}/prices/history
                     (?variant=&days=). Each history point carries its own source +
                     source_updated_at — never blend sources into one canonical number.
data/                GITIGNORED — 20,391 card images, 40 MB FAISS index, SQLite db, 101 real scans
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
2. **Phase 3 full grading** (corners, edges, surface, grading EV) — blocked on labelled graded-card
   data and graded-card prices. Centering is the one sub-grade measurable without it.
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
