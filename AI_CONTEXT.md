# AI_CONTEXT.md — bring any AI model up to speed on this project

> **Purpose:** this is the single file to hand an AI assistant so it understands what this project
> is, what has been built, what has been *measured*, and what not to break. Read it top to bottom
> before proposing anything.
>
> **Keep it current.** Update this file after any change that alters architecture, measured
> results, or the roadmap. A stale onboarding doc is worse than none, because it is trusted.
>
> Last updated: **2026-08-20**

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

## 2. Current state (2026-08-20)

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
| 4 | Bulk cataloger: many cards per photo | ✅ Complete (§14) |
| 5 | Deal sniper + sealed EV | In progress — deal sniper / rip-vs-flip shipped (§12); deal alerts + sold-comps evidence shipped (§13); sealed flip-edge shipped (§15); sealed purchase ledger + profit tracker + Google Sheets sync (OAuth) shipped (§16); rip EV (expected pull value) still planned — needs pull-rate data |
| UI | Responsive UI overhaul — refined dark-glass + desktop sidebar + Framer Motion (phone→any desktop) | ✅ Complete 2026-08-20 (§17) — frontend-only; 126 tests green; 105-scan baseline untouched |
| UI+ | Living UI — Dashboard (Home) landing (animated count-up KPIs + allocation donut + movers bars), Cmd/Ctrl+K command palette + keyboard shortcuts, toast system, animated gradient mesh | ✅ Complete 2026-08-20 (§18) — frontend-only; 146 tests green; 105-scan baseline untouched |
| 6 | Set-completion optimizer | Planned |
| 7 | Counterfeit detector | Planned |

**Tests:** 568 backend (pytest) + 146 frontend (vitest).

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
                     listings_provider.py (Protocol + ListingQuote + SoldComp) + ebay_listings.py
                     (EbayListingsProvider — eBay **Finding API** findItemsByKeywords, one
                     SECURITY-APPNAME query param, no OAuth; catalog lookup wired so the keyword
                     is card name + number; degrades to [] without a key, never raises. Also
                     fetch_sold_listings → findCompletedItems w/ SoldItemsOnly=true,
                     SERVICE-VERSION=1.13.0 (the EndedWithSales bug fix), EndTimeSoonest — the
                     3 most-recent eBay SOLD listings as on-demand evidence; NOT persisted, no
                     snapshot writes) + listings_service.py (ListingsService — immutable
                     ListingSnapshot dedupe, lowest_price None-not-0.0, previous_listing_ids by
                     fetched_at-grouping) + sold_comps_api_models.py (SoldCompOut +
                     SoldCompsResponse — Pydantic v2, from_attributes)
  alerts/            engine.py (AlertEngine — 6 alert types incl. deal, per-watch SAVEPOINT
                     isolation, never-raises), notify.py (NotificationService — in-app/push/email,
                     degrades gracefully per channel), api_models.py (Pydantic wire models)
  deals/             engine.py (DealEngine — read-only rip-vs-flip: rip_edge = raw_market −
                     listing.price; flip_edge_to_9/10 = graded comp − listing.price − grading_fee;
                     thresholds filter noise, missing inputs null the edge, never a fabricated $0;
                     ranked by deal_score desc, nulls last; writes nothing) +
                     api_models.py (DealAssessmentOut, DealsResponse — Pydantic v2)
  collection/        store.py — add/remove/list/valuation + portfolio/summary/set_cost_basis
  recognition/       detectors.py (detect_candidates = single-card path; detect_all_quads = Phase 4
                     multi-quad: all canny+otsu_rect contours, both Otsu polarities, IoU NMS),
                     rectify.py, encoder.py, index.py, ocr.py, fusion.py, service.py
                     (recognize = single-card; recognize_many = Phase 4 batched: rectify each quad,
                     embed_many ONCE, index.search per vector, _fuse_for per crop, parallel OCR pool —
                     one deep-copied reader per worker since RapidOCR is not thread-safe;
                     persists the rectified crop to data/rectified/ + stamps scan_logs.variant)
  grading/           store.py (GradingLabelStore — self-annotation), upside.py (GradingUpsideService —
                     the raw/PSA-9/PSA-10 spread, honest nulls, never a prediction)
  scans/             store.py — logs every scan as ground truth (rectified_path + variant columns;
                     record_batch = Phase 4 one photo → N rows sharing image_path, per-crop commit,
                     batch_id+batch_index stamped; accuracy() is batch-aware — one representative
                     per batch_id, NULL batch_id rows are singleton batches so the 105-scan baseline
                     is not inflated)
  api.py             FastAPI, cli.py  CLI
backend/scripts/     evaluate_recognition.py, evaluate_detection.py, spot_check.py
frontend/src/        api/, lib/ (format, cameraCrop, time — shared relativeTime), components/
                     (CameraCapture, ScanResult, CandidatePicker, PriceLine, CornerAdjust,
                     PortfolioView, PriceChart, GradingUpside — the spread panel; ScanResult hosts
                     the self-annotation form; AppShell — 6-tab nav Scan/Vault/Alerts/Deals/Browse/
                     More, Alerts-first; CardDetail — listings + per-listing deal-score chips + the
                     SoldComps "Recent sold (eBay)" evidence block under the market price; Browse,
                     AlertsFeed (type-filter incl. a Deals chip + 💰 deal icon), WatchCardSheet (6
                     alert types incl. a Deal chip), Deals — the Phase 05 deal feed, More — the
                     Phase 3c alert/watchlist UI; BulkPane — Phase 04 bulk-cataloger mode:
                     single↔bulk toggle in the Scan pane, one binder-page capture → CSS grid of N
                     ScanResult cells, per-cell variant selector + fix-ups, bulk-add to collection;
                     single-card path unchanged)
frontend/public/     manifest.webmanifest, icon-192/512/icon-maskable-512.png, icon-source.svg
frontend/scripts/    gen-icons.py (rasterize icon-source.svg → PNGs)
site/                Next.js 15 marketing app — app/sections/ (Hero, Problem, Pipeline, Roadmap,
                     Grading, Alerts, Deals, Stack, Footer), app/sections/data.ts (copy + roadmap
                     rows), providers.tsx (Lenis + GSAP ScrollTrigger), next.config.mjs (static
                     export + basePath)
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
api.py Phase 05 endpoints: GET /cards/{card_id}/deals?variant= (ranked rip/flip deals, honest
                     listings_unavailable / listings_empty flags, thresholds in response) +
                     GET /deals?card_ids=&limit= (cross-card feed defaulting to the active
                     watchlist; assesses the "" variant per card). DealEngine is read-only —
                     no snapshot writes. CLI: find-deals (one-shot, prints ranked deals; honest
                     "no listings source key" / "no active listings" messages).
api.py Phase 05b endpoints: GET /cards/{card_id}/sold-comps?variant=&limit=3 (the 3 most-recent
                     eBay SOLD listings as on-demand evidence backing the raw market price;
                     honest sold_comps_unavailable / sold_comps_empty flags; NOT persisted —
                     no snapshot writes) + deal alert type (alert_type="deal", 422 if card_id
                     missing). AlertEngine gains an optional deal_engine collaborator; _eval_deal
                     mirrors _eval_new_listing's last_seen_listing_ids baseline dedupe (first poll
                     never fires, fires only for NEW listings clearing rip/flip thresholds, baseline
                     always advances). The poll loop + CLI check-alerts inject the shared DealEngine.
api.py Phase 04 endpoints: POST /recognize/batch (one binder-page photo → N independent RecognizeOut
                     + a uuid4 batch_id grouping them; detect_all_quads → cap max_cards [1,18] →
                     recognize_many → latest_price per confident card; per-card statuses NEVER
                     collapsed into one batch status; not_found → card/price null, never $0;
                     does NOT write scan_logs — the client logs per card via POST /scans threading
                     batch_id+batch_index+rectified_path). Additive scan_logs.batch_id (indexed) +
                     batch_index via the migration helper; 105 existing rows stay NULL.
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
(lifespan handler is the clean replacement); the eBay listings adapter was upgraded to the real
Finding API in Phase 05 (§12) — restock/new_listing/auction alerts now flow when
`CARDPLATFORM_LISTINGS_API_KEY` (eBay App ID) is set; `previous_listing_ids` can merge two
same-clock-tick fetches (acceptable at a 15-min poll cadence); numeric `listing_id` assumed for the
auction dedupe `LIKE`.

**Sacred constraints held:** no ad-hoc price resolution; snapshots immutable (listings too);
staleness surfaced; honest empty states (no `$0`, never fabricate events, channels degrade silently);
no `data/` contents deleted; `func.lower(...).like` for text search; `UtcDateTime` for tz-aware
columns; `""` sentinel for unique-constraint columns that may lack a source timestamp.

---

## 12. Phase 05 — deal sniper / rip-vs-flip (deal-sniper leg)

Shipped 2026-08-03 on `main`. **462 backend + 96 frontend tests.** Joins the 3b graded-price leg and
the 3c listings leg into an evaluation: **is this active listing a deal — to rip (buy below raw sold-comp
market) or to flip (buy raw, grade, sell at the PSA-10 comp)?** — with honest nulls whenever an edge
input is missing. The same "never fake missing data" value throughout: missing raw/graded nulls the
edge they feed (never `$0`, never a fake profit), and listings degrade honestly when no source key is
set. 105 real scans preserved; raw `PriceSnapshot` / `GradedPriceSnapshot` and recognition untouched.

**The deal model (read-only `DealEngine.assess(card_id, variant) -> list[DealAssessment]`):**
`rip_edge = raw_market.price − listing.price`; `flip_edge_to_9 = psa9.market − listing.price −
grading_fee`; `flip_edge_to_10 = psa10.market − listing.price − grading_fee`. A listing is `is_rip`
iff `rip_edge >= deal_rip_min_abs AND rip_edge >= deal_rip_min_pct * raw_market.price` (default `$2` /
`0.10`); `is_flip` iff `flip_edge_to_10 >= deal_flip_min_abs` (default `$20`). `deal_score =
max(rip_edge or 0, flip_edge_to_10 or 0)`, ranked desc, nulls last. Edges are **indicative leads** —
eBay keyword listings carry seller-mislabel noise; the UI says "investigate before buying". The
engine writes nothing (deals are computed on demand from the latest snapshots, so they never go
stale in storage — no `deal_snapshots` table).

What shipped (TDD, subagent-driven; inline spec+quality reviews T1–T5):
- **T1 — eBay Finding API adapter (the realness leg).** The 3c `EbayListingsProvider` called the
  Browse API (`item_summary/search`) with the key faked as a static bearer — Browse needs real OAuth,
  so it never returned listings. Replaced with the **Finding API** `findItemsByKeywords`: one
  `SECURITY-APPNAME` (eBay App ID) query param, no OAuth. Parses the array-wrapped Finding JSON
  (`findItemsByKeywordsResponse.searchResult.item[]`, every field in a single-element array). A
  `_catalog_lookup(session)` helper resolves card_id → (set_name, number, card_name) and is wired
  into the API endpoint, the in-process `_poll_loop`, and the CLI `check-alerts`, so the keyword is
  the card's real name + number (not the `"base1-4"` slug, which returned nothing) — **this also
  unblocks the 3c restock/new_listing/auction alerts**. Never-raise discipline kept (no key → `[]`;
  404/401/bad-JSON terminal-one-attempt; 5xx/429/transport retry → `[]`). Items missing a price are
  **skipped, not fabricated**; `auction_end_at` is set only for auctions. Three deal-threshold
  settings added.
- **T2 — read-only DealEngine.** `deals/engine.py` — uses only `PriceService.latest_price`,
  `GradedPriceService.latest_graded`, `ListingsService.latest_listings` (no ad-hoc resolution, no
  snapshot writes). Missing inputs null the edge they feed; thresholds filter noise without
  manufacturing deals.
- **T3 — API + CLI.** `deals/api_models.py` (Pydantic v2) + `GET /cards/{id}/deals?variant=` (ranked
  deals, honest flags, thresholds in response) + `GET /deals?card_ids=&limit=` (cross-card feed
  defaulting to the active watchlist; assesses the `""` variant per card) + `cardplatform find-deals`
  CLI (honest "no listings source key" / "no active listings" messages).
- **T4 — frontend.** 6th bottom-nav **Deals** tab (`Deals.tsx` — search a card or pull watched cards
  → ranked deal feed with rip/flip edges, deal chips, staleness, "investigate before buying" caveat;
  honest empty states: set-a-key / no active listings / no market price / no graded comps) +
  per-listing deal-score chips on `CardDetail`. `relativeTime` extracted to `lib/time.ts` (shared
  with `AlertsFeed`); new `auctionCountdown` helper (the existing one was past-elapsed only).
  `formatMoney`'s no-comma convention preserved.
- **T5 — site.** New scroll-animated `Deals` section (GSAP scrub + Framer reveal, rip-vs-flip
  diagram, `prefers-reduced-motion` static, JS-off visible) with the honest "Deal edges are
  indicative leads from marketplace keyword search, not guaranteed arbitrage — always verify the
  listing" caption. Roadmap row 05 → in-progress ("Deal sniper (rip-vs-flip) shipped — sealed EV
  still planned"). Rebuilt → `docs/` (`.nojekyll` + `docs/superpowers/` preserved).

**Key acquisition:** a free eBay developer account at `developer.ebay.com` → My Apps → create app →
the App ID (Client ID) is the `SECURITY-APPNAME`. Set as `CARDPLATFORM_LISTINGS_API_KEY`. Until set,
the whole deal surface is honestly empty — the phase ships regardless (the verified path is the
honest-empty path, same as graded prices in 3b).

**Documented follow-ups (not solved):** sealed-product EV (Phase 05's other leg — needs a
sealed-product price provider); deal alerts (compose the 3c alert engine with this evaluator);
persisting deal scores / deal history (a `deal_snapshots` table — deals are on-demand now);
multi-source listings (only eBay; the Protocol keeps a second source swappable); full-catalog deal
scan (the feed scopes to watched + searched cards); eBay OAuth / Browse API (Finding API's one-key
auth is simpler; Browse is an upgrade path).

**Sacred constraints held:** no ad-hoc price resolution (only `latest_price`/`latest_graded`/
`latest_listings`); snapshots immutable; **DealEngine is read-only (no writes, no new table)**;
staleness surfaced; honest empty states (no `$0`, never a fabricated edge); no `data/` contents
deleted; `func.lower(...).like` for text search.

---

## 13. Phase 05b — deal alerts + eBay sold-comps evidence

Shipped 2026-08-04 on `main`. **485 backend + 102 frontend tests.** Two additive legs on top of
Phase 05, both holding the sacred constraints — no schema change, no new table, no snapshot writes.
105 real scans preserved; raw `PriceSnapshot` / `GradedPriceSnapshot` / `ListingSnapshot` and
recognition untouched.

**Leg 1 — deal alerts (push instead of pull).** Composes the 3c `AlertEngine` with the Phase 05
read-only `DealEngine` so a *new* active listing clearing the rip/flip thresholds fires an alert,
reusing the 3c poll loop, notification channels, and the per-watch `last_seen_listing_ids` baseline
dedupe.

- **A `deal` watch fits the existing `Watch` model with NO new columns / NO migration.**
  `alert_type="deal"`, `card_id`+`variant` set (variant defaults `""`), `target_price=None`,
  `drop_at=None`, unique key `(card_id, variant, "deal", None, None)`. Thresholds are the global
  `deal_*` settings (no per-watch thresholds).
- **`AlertEngine.__init__` gains an optional `deal_engine=None`** keyword param — `None` means deal
  watches never fire (keeps the 3c callers + tests that construct without it green). `_eval` gains a
  `deal` dispatch branch → `_eval_deal(w, now)`.
- **`_eval_deal` mirrors `_eval_new_listing`'s baseline-dedupe:** reads `DealEngine.assess(...)`
  (read-only, never raises), `curr_deal_ids = {a.listing_id for a in assessments if a.is_rip or
  is_flip}`. **First poll (prev baseline empty) writes the baseline and fires nothing** — never fire
  on the first poll. Subsequent polls fire for `new_ids = curr_deal_ids - prev_ids`; the baseline
  always advances (even to empty) so a listing that *stops* being a deal can't re-fire. A non-deal
  poll produces empty `curr_deal_ids` → empty baseline, never fires.
- **Deal message + context.** One-line honest message (leads with the larger of rip/flip edge,
  "Verify before buying.") and a JSON context (listing_id, url, listing_price, currency, condition,
  rip_edge, flip_edge_to_10, is_rip, is_flip, deal_score, raw_market). Reuses the immutable
  `AlertEvent` + notifier; `_fire` unchanged.
- **Watchlist API:** `_ALERT_TYPES` += `"deal"`; 422 if `alert_type=="deal"` and `card_id is None`.
- **Wiring:** `_poll_loop` builds one shared `ListingsService` + `DealEngine(session, settings,
  listings_service=listings)` and injects `deal_engine=...` into `AlertEngine`. `cli.py check-alerts`
  does the same, so `python -m cardplatform.cli check-alerts` now evaluates deal watches.

**Leg 2 — eBay sold-comps evidence (backing the raw market price).** Surfaces the 3 most-recent eBay
**sold** listings for a card as on-demand evidence ("market $120 because these 3 just sold at $118 /
$121 / $119"). NOT persisted — no `SoldCompSnapshot` table, no snapshot writes; on-demand read.

- **`EbayListingsProvider.fetch_sold_listings(card_id, variant, limit=3)`** via the Finding API
  `findCompletedItems` with `itemFilter(0).name=SoldItemsOnly`/`value=true`,
  `sortOrder=EndTimeSoonest`, `SERVICE-VERSION=1.13.0`. **The version is load-bearing:** the legacy
  `1.0.0` returns `sellingState="Ended"` for sold items (eBay bug #185); `1.13.0` returns the
  correct `"EndedWithSales"`. `_parse_completed` **skips any item whose `sellingState !=
  "EndedWithSales"`** and any price-less item (never fabricate a sale, never a fake `$0`). Same
  never-raise discipline as `fetch_listings` (no key → `[]`; 404/401/bad-JSON terminal one attempt;
  5xx/429/transport retry → `[]`).
- **`SoldComp` frozen dataclass** (`prices/listings_provider.py` alongside `ListingQuote`) +
  `sold_comps_api_models.py` (`SoldCompOut` + `SoldCompsResponse`, Pydantic v2 `from_attributes`).
- **`GET /cards/{card_id}/sold-comps?variant=&limit=3`** — honest `sold_comps_unavailable` (= no
  `CARDPLATFORM_LISTINGS_API_KEY`, mirroring the deals/listings `*_unavailable` contract) +
  `sold_comps_empty` (= fetched but found none). Both false when comps return. `limit` clamped to
  `[1, 10]`, default 3.
- **Frontend** — `SoldComps.tsx` ("Recent sold (eBay)" evidence block: `formatMoney(price)` +
  `relativeTime(sold_at)` + condition + outbound url, honest empty states) rendered in `CardDetail`
  right under the market-price block. `getSoldComps(cardId, variant, limit=3)` in the client;
  `SoldComp` + `SoldCompsResponse` types. `WatchCardSheet` gains a 6th Deal chip
  (`needsCard`/`needsListings`, no conditional fields); `AlertsFeed` gains a Deals filter chip +
  `deal: "💰"` icon.

**Deprecation caveat (documented, not blocking):** eBay **deprecated `findCompletedItems` on
2020-10-15** in favor of the Marketplace Insights API (Limited Release — needs approval, not viable
for a solo free-tier app). The deprecated endpoint still responds for free App IDs today; the adapter
degrades to `[]` on any failure (no key, transport, retirement, unexpected shape) and the UI shows an
honest "recent sold comps unavailable". A future Marketplace Insights migration is a documented
follow-up, not this phase.

**Sacred constraints held:** no ad-hoc price resolution (only `DealEngine.assess` /
`PriceService.latest_price`); **no snapshot writes for sold comps** (on-demand evidence only);
**no schema change, no new table** (a `deal` watch fits the existing `Watch` model);
staleness surfaced (`sold_at`); honest empty states (no `$0`, never a fabricated sale, never a
fabricated deal event); no `data/` contents deleted; snapshots still immutable; `func.lower(...).like`
for text search.

---

## 14. Phase 4 — bulk cataloger (many cards per photo)

Shipped 2026-08-04 on `main`. **505 backend + 106 frontend tests.** One binder-page photo → N
identified + valued cards in one scan, with a batch review grid where each card is fixed up
independently. The phase splits **detection** (run once → N non-overlapping quads via IoU NMS)
from **recognition** (per-quad, batched embedding, parallel OCR). Additive to the single-card
pipeline — the single-card `POST /recognize` + `detect_candidates` path is byte-for-byte unchanged,
and the 105-scan baseline replays with **0 regressions**. No external API added this phase.

**Architecture:** `detect_all_quads` collects every card-shaped contour from `canny` +
`otsu_rect` (both Otsu polarities), IoU-NMS-dedupes (no NMS existed anywhere before) → N quads.
`recognize_many` rectifies each, calls `embed_many` **once** (the encoder already supported
batching — `embed()` delegates to it), searches the index per vector, then fuses + OCRs each
winning crop. OCR (~1 s/crop) is parallelized across a `ThreadPoolExecutor` with one
`copy.deepcopy` reader per worker (RapidOCR is not thread-safe). `POST /recognize/batch` caps
to `max_cards` (default 9, clamped `[1,18]`), resolves price per confident card via
`PriceService.latest_price`, returns `BatchRecognizeOut{batch_id, count, results: [RecognizeOut]}`.
Per-card statuses are NEVER collapsed into one batch status. The client logs each card via the
existing `POST /scans`, threading `batch_id` + `batch_index`.

**Recognition is still the arbiter, not geometry.** A card-shaped sleeve/glare slot still embeds
to a low `visual_score` and stays `not_found` per crop — never auto-promoted on geometry. The
`-inf` best-score floor and the "found a card-shaped quad != found the card" invariant hold per
crop. `MAX_AREA_FRACTION=0.98` is kept — it rejects the whole-frame blob adaptive thresholding
produced on 101/101 real scans; a binder card is ~0.11 of a 9-card frame.

What shipped (TDD, subagent-driven; inline spec+quality reviews per task):
- **T1 — multi-quad detection + IoU NMS.** `recognition/detectors.py` `detect_all_quads` +
  `_all_polygon_quads`/`_all_rotated_rect_quads`/`_canny_quads`/`_otsu_rect_quads` (multi-quad
  siblings of the single-quad `_largest_*` helpers — iterate all contours above
  `MIN_AREA_FRACTION`, not just the first) + `_iou` (convex-quad IoU via
  `cv2.intersectConvexConvex`) + `_nms` (largest-first greedy, threshold 0.3). `detect_candidates`
  and all constants unchanged. 6 new tests on synthetic grids.
- **T2 — batched recognition.** `recognition/service.py` `recognize_many` (additive; rectify →
  `embed_many` once → per-vector search → per-crop `_fuse_for` with a per-worker reader) +
  `_fuse_for` refactored to accept an optional `reader=None` (the only change to the single-card
  path — `recognize` calls it with no reader, unchanged). `config.py` `batch_ocr_workers` (default
  2, clamped `[1,4]` via a pydantic v2 `field_validator`). 4 new tests.
- **T3 — batch scan logging.** `ScanLog` gains nullable `batch_id` (indexed) + `batch_index`,
  added to the model AND `_ADDITIVE_COLUMNS` in the same change (schema drift between them 500s).
  `ScanStore.record_batch` writes the source photo once → N rows sharing `image_path`, per-crop
  commit, logs `not_found` too. `accuracy()` is batch-aware: one representative per `batch_id`
  (first by id); NULL-`batch_id` rows are keyed `("singleton", row.id)` so each of the 105
  single-card scans still counts as its own batch — the baseline is NOT inflated. `ScanAccuracy`
  fields unchanged. 3 new tests.
- **T4 — batch endpoint + wire types.** `POST /recognize/batch` (mirrors `POST /recognize`
  field-for-field; `detect_all_quads` → `max_cards` clamp → `recognize_many` → `latest_price` per
  confident card; `not_found` → `card=None, price=None`, never `$0`; `max_cards` 422 on >18;
  imports the `detectors` module so the test's monkeypatch on `detectors.detect_all_quads` takes
  effect). `BatchRecognizeOut` + frontend `BatchRecognizeResponse` + `batchRecognize` client;
  `recordScan` extended with optional `{batch_id, batch_index, rectified_path, variant}`. 4 new tests.
- **T5 — batch review grid.** `AppShell.tsx` `BulkPane` — single↔bulk toggle in the Scan pane
  (default single; single-card branch verbatim), one binder-page capture → CSS grid of N
  `ScanResult` cells (reused unchanged) with per-cell variant selector (refetches price for that
  cell on change) + per-cell fix-ups, bulk-add to collection via the existing `addToCollection`
  (duplicates merge). `formatMoney(null)` → `—`, never `$0.00`. 4 new tests.
- **T6 — eval harness.** `scripts/make_batch_fixtures.py` (synthetic 3×3 + 2×2 binder pages with
  per-card ground-truth JSON — additive under `data/scans/batch_fixtures/`, 4 files) +
  `evaluate_detection.py` `--batch` mode (per-card IoU>0.5 recall, fails if any page <0.8; the
  single-card 105-scan path is untouched). Recall 1.00 on both fixtures. 3 new tests.
- **T7 — integrate + verify + ship.** Two harness fixes: `evaluate_detection.py` now calls
  `database.create_all()` at startup (it opened a stale DB that lacked the T3 `batch_id` column
  — `select(ScanLog)` 500s without the migration; the app/cli self-heal via `create_all()` but the
  script didn't) and unpacks `recognize()`'s `(result, centering)` tuple (a pre-existing Phase 3a
  breakage — the harness hadn't been run since centering was added). Neither was a Phase 4
  regression. Baseline green: 105 scans, 0 regressions. Docs + memory updated, merged, pushed.

**Open questions resolved (auto-mode defaults, in the design spec):** synthetic fixtures (real
binder capture is a documented follow-up — we cannot claim real-photo coverage without real
fixtures); extend canny+otsu_rect+IoU NMS (defer line/segment grid); `batch_ocr_workers` default
2 clamped `[1,4]`; all N rows share the source `image_path`; `max_cards` default 9 clamped
`[1,18]`; default `normal` variant + per-cell selector; bulk-add merges duplicates (per-lot
cost-basis deferred from Phase 2); in-pane mode toggle (not a 7th nav tab — avoids 6-item
overflow on narrow phones); per-crop commit.

**Documented follow-ups (not solved):** line/segment grid detection (a measured follow-up if
blob+NMS underperforms on real binder photos); real-binder fixture capture (synthetic only this
phase); per-lot cost-basis model (still deferred from Phase 2); persisting a parent batch row
(the shared `batch_id` + `batch_index` on each row is sufficient grouping); auto-rotating/
flattening the binder page (assume the photo is oriented like the cards).

**Sacred constraints held:** no ad-hoc price resolution (only `latest_price`); honest empty
states (no `$0`, never a fabricated card or status, per-card statuses never collapsed);
snapshots immutable; no `data/` contents deleted (only additions under
`data/scans/batch_fixtures/`); **additive schema only** (nullable `batch_id`/`batch_index` via
the idempotent migration helper, 105 rows stay NULL); recognition is the arbiter (low-visual-score
kept quads stay `not_found`); single-card path unchanged; the 105-scan baseline replays with 0
regressions.

---

## 15. Phase 05c — sealed-product flip-edge

Shipped 2026-08-19 on `main`. **530 backend + 115 frontend tests.** The flip-side of the
Phase 05 deal sniper, applied to sealed products (booster boxes, ETBs, etc.) that have no
`card_id`/`variant` — they are keyed by a free-text query. The same "never fake missing data"
discipline: `flip_edge` is null when `sealed_market` (median sold comp) is None or the listing
has no price; `is_flip` is False when `flip_edge` is None; `deal_score` is null-last. No
recognition code changed this phase — the 105-scan baseline replays with **0 regressions**.

**The deal model (read-only `SealedDealEngine.assess(query, limit) -> SealedDealResult`):**
`sealed_market = median(sold_comp_prices)` (None if no sold comps → all `flip_edge` null);
per listing: `flip_edge = sealed_market − listing.price` (None if either missing);
`is_flip = flip_edge is not None AND flip_edge >= sealed_flip_min_abs AND
flip_edge >= sealed_flip_min_pct * sealed_market` (default `$20` / `0.05`);
`deal_score = flip_edge if flip_edge is not None else None`, sorted desc, nulls last.
`sealed_market` is a **median** (robust to one outlier comp), an **indicative lead**
("investigate before buying"), not guaranteed arbitrage — the same framing as the Phase 05
deal sniper. Selling fees are intentionally NOT subtracted (gross edge), matching
`DealEngine`; the UI says so. The engine writes nothing (on-demand from the latest sold comps,
so deals never go stale in storage — no `sealed_snapshots` table).

What shipped (TDD, subagent-driven; inline spec+quality reviews T1–T5):
- **T1 — `SealedListingsProvider` Protocol + eBay `*_by_query` fetch + DRY refactor.** New
  `sealed/provider.py` defines `SealedListing` / `SealedSoldComp` (frozen dataclasses, no
  `card_id`/`variant` — they carry `query`) and the `SealedListingsProvider` Protocol
  (`fetch_listings_by_query`, `fetch_sold_listings_by_query`). The eBay adapter
  (`prices/ebay_listings.py`) gains `fetch_listings_by_query` (Finding API
  `findItemsByKeywords`) and `fetch_sold_listings_by_query` (`findCompletedItems` +
  `EndedWithSales`-gating, `sortOrder=EndTimeSoonest`, `SERVICE-VERSION=1.13.0`). Shared
  `_extract_listing_fields` / `_extract_sold_fields` helpers are DRY-extracted so the
  existing single-card `_parse` / `_parse_completed` paths are byte-for-byte unchanged. Same
  never-raise discipline (no key → `[]` without a network call; 404/401/bad-JSON terminal one
  attempt; 5xx/429/transport retry → `[]`); price-less items skipped, never fabricated;
  `auction_end_at` set only for auctions.
- **T2 — read-only `SealedDealEngine`.** `sealed/engine.py` composes a `SealedListingsProvider`
  + `settings`; never resolves a price ad hoc (the only "price" is the median sold comp,
  which IS the market reference). `SealedPricePoint` / `SealedThresholds` /
  `SealedDealAssessment` / `SealedDealResult` frozen dataclasses. Missing inputs null the
  edge they feed; thresholds filter noise without manufacturing deals.
- **T3 — API + CLI + wire models.** `sealed/api_models.py` (`SealedPricePointOut`,
  `SealedThresholdsOut`, `SealedDealAssessmentOut`, `SealedDealsResponse`, Pydantic v2
  `from_attributes`) + `GET /sealed/deals?query=&limit=` (ranked deals, honest flags:
  `listings_unavailable` vs `listings_empty` vs `comps_unavailable` vs `comps_empty`,
  thresholds in response) + `cardplatform find-sealed-deals --query --limit` CLI. API
  `limit` is `Query(20, ge=1, le=50)` (rejects out-of-range with 422); CLI clamps
  (`max(1, min(limit, 50))`) for friendliness — documented difference.
- **T4 — frontend.** 7th bottom-nav **Sealed** tab (`SealedDeals.tsx` — search a sealed query
  → ranked flip-edge feed with flip chips, sealed-market banner, staleness, "investigate
  before buying" caveat; honest empty states: set-a-key / no active listings / no sold comps
  / no market price) + `getSealedDeals(query, limit)` client + `SealedDealAssessment` /
  `SealedPricePoint` / `SealedThresholds` / `SealedDealsResponse` types. Reuses the existing
  `.deal-*` styles; `formatMoney`'s no-comma convention preserved.
- **T5 — site + docs + ship.** Roadmap row 05 → "sealed flip-edge shipped; rip EV still
  planned — needs pull-rate data". `AI_CONTEXT.md` §2 + new §15 (this section). `PROJECT.md`
  roadmap + next-step. Design-spec reconciliation (§4 `deal_score` null-last to match §7;
  §8 API-rejects vs CLI-clamps). Rebuilt → `docs/` (`.nojekyll` + `docs/superpowers/`
  preserved).

**Sacred constraints held:** no ad-hoc price resolution (only the median sold comp via the
provider); **read-only engine (no writes, no new table, no schema change)**; degrade to `[]`
never raise; honest empty states (no `$0`, never a fabricated edge or sale, distinct
unavailable/empty flags); staleness surfaced (`sold_at`); no `data/` contents deleted;
recognition + 105-scan baseline untouched (0 regressions).

**Documented follow-ups (not solved):** rip EV / expected pull value (needs pull-rate data +
a product master — the "product" is currently the user's free-text query, no `SealedProduct`
master yet); a sealed snapshot table (deals are on-demand now, never stale in storage);
TCGplayer sealed API (eBay Finding API is the only source; a second swappable source is the
upgrade path); a separate `sealed_*` API key if a non-eBay sealed source is added.

---

## 16. Phase 05d — Sealed purchase ledger + profit tracker + Google Sheets sync

Shipped 2026-08-20 on `main`. **568 backend + 126 frontend tests.** A reseller-facing
sealed-product purchase ledger on top of the 05c sealed flip-edge: log what you bought
(query, product type, quantity, cost per unit, source, listing url, notes, bought-at),
refresh market valuations on demand from the 05c
`EbayListingsProvider.fetch_sold_listings_by_query` sold-comps median, and mirror the
ranked profit ledger to a Google Sheet via OAuth. The same "never fake missing data"
discipline throughout: profit is `—` until a valuation exists (never `$0`); valuations are
append-only (insert never update); Sheets is a mirror that degrades to `not_configured`
without a network call. No recognition code changed this phase — the 105-scan baseline
replays with **0 regressions**.

**Two new tables, auto-provisioned by `Database.create_all()` (no migration):**
- **`sealed_purchases`** (user-editable) — `query`, `product_type`, `quantity`,
  `cost_per_unit`, `source`, `listing_url`, `notes`, `bought_at`, `created_at`.
- **`sealed_valuations`** (append-only market snapshots) — `purchase_id` FK,
  `value_per_unit`, `source="ebay_sold_median"`, `comp_count`, `fetched_at`. Insert never
  update — the history of market reads accrues like `PriceSnapshot`.

**`LedgerService`** — CRUD over `sealed_purchases` + on-demand valuation refresh (reuses
the 05c `EbayListingsProvider.fetch_sold_listings_by_query` + `statistics.median` to write
a new `sealed_valuations` row) + read-only profit: the latest valuation is `max(id) per
purchase`; `profit = value×qty − cost×qty`; `None` if unvalued; div-zero guard on
`profit_pct`. Sacred: profit reads the latest *persisted* valuation — never an ad-hoc fetch.

**Routes** — `GET/POST/DELETE /sealed/ledger`, `POST /sealed/ledger/valuate` (refresh all),
`POST /sealed/ledger/{id}/valuate` (refresh one), `POST /sealed/ledger/sync` (Sheets
mirror). **CLI** — `log-sealed-purchase`, `list-sealed-ledger`, `valuate-sealed-ledger`,
`sync-sealed-ledger`. **Frontend** — 8th bottom-nav **Ledger** tab (`SealedLedger.tsx` —
log form + ranked ledger with per-row profit, Refresh valuations, Sync to Google Sheets;
honest `—` for unvalued rows, never `$0`).

**Google Sheets setup (OAuth, gitignored secrets).** Create an OAuth Desktop client in
Google Cloud Console → download the client secret JSON to `data/credentials.json`; set
`CARDPLATFORM_GOOGLE_SHEET_ID` to the target sheet's ID. First `sync` opens a browser
sign-in via `google-auth-oauthlib` `InstalledAppFlow` (scope `spreadsheets`) and stashes the
token at `data/google_token.json`. Both `data/credentials.json` and `data/google_token.json`
are gitignored. Sync is a **full-tab overwrite** (clear + write header + rows), idempotent.
`is_configured()` = sheet_id set AND secret file exists; not configured →
`synced=False, reason="not_configured"` (no network, no raise). The Sheet is a mirror, never
a source of truth.

**Sacred constraints held:** profit reads the latest *persisted* valuation (never ad hoc);
valuations append-only (insert never update); honest empties (`—` / not-configured, never
`$0`); Sheets is a mirror that degrades to not-configured; providers degrade never raise;
no ad-hoc price resolution (the only "price" is the 05c sold-comps median); no `data/`
deletion; recognition + 105-scan baseline untouched (0 regressions).

**Documented follow-ups (not solved):** the 8-tab bottom nav is tight on narrow screens
(minor, no blocker); rip EV (expected pull value) still data-blocked (no pull rates) —
deferred, mirrors 05c; a `SealedProduct` master (the "product" is currently the user's
free-text query).

## 17. Responsive UI overhaul — refined dark + responsive + polished motion (2026-08-20)

A full visual + responsive overhaul of the **frontend only**
([plan](docs/superpowers/plans/2026-08-20-responsive-ui-overhaul.md)). Backend, `data/`, and the
105-scan baseline are untouched. **126 frontend tests stayed green throughout; build clean.**
The 8-tab bottom-nav "tight on narrow screens" follow-up from §16 is now resolved on desktop (the
sidebar replaces it ≥1024px) and remains tight only on phones.

- **Responsive shell** — `frontend/src/lib/useIsDesktop.ts` (matchMedia `min-width:1024px`,
  jsdom-safe → `false` in tests so the test DOM keeps the mobile bottom-nav) is the single source of
  truth: AppShell mounts EITHER a desktop left sidebar (`<aside class="app-sidebar">`, reusing the
  existing `TabButton` + glyphs so the 8 tab accessible names are byte-identical) OR the mobile
  `.bottom-nav` — never both, so `getByRole("button", { name: "Scan" })` still resolves to one
  element. Desktop: sidebar pinned left, content max-width 1180px centered with `clamp()` padding,
  sticky glass header; `@media (min-width:1440px)` widens to 264px sidebar + 1320px content. Mobile
  layout untouched.
- **Polished motion (Framer Motion 12, new dep)** — `frontend/src/components/motion.tsx` exports
  `PageTransition` / `StaggerList` / `StaggerItem` / `MotionCard` + shared variants, all
  `useReducedMotion`-gated. AppShell wraps each view branch in `<AnimatePresence mode="wait">` +
  `<PageTransition>` (fade+slide, keyed by view / `"card"` for the CardDetail overlay).
  `WatchCardSheet` overlay fades in and the sheet springs in (reduced-motion: opacity-only). List
  surfaces (alerts/deals/browse/sealed/ledger) stagger their items on mount via `motion.ul` +
  `staggerContainer` → `motion.li` + `staggerItem`, with hover-lift (`y:-4`) / tap-scale. Portfolio
  table rows are NOT motion-wrapped (table-row constraint) — CSS hover only; the valuation summary
  cards stagger.
- **Refined dark-glass identity** — glass surfaces (backdrop-filter + hairline border + top-highlight
  gradient) layered on the existing card classes (deal-card, alert-row, browse-result, bulk-cell,
  channel-card, watchlist-row, result, camera-frame, sheet, portfolio-table-wrap, grading-upside,
  centering, sold-comps, card-detail); primary CTAs get the yellow gradient fill + glow; RIP/flip
  chips and up/down pills get gradient treatments; inputs get glass insets + focus rings. All
  additive CSS — no class renamed, the flat `--surface` backgrounds remain as the no-backdrop
  fallback. New tokens: `--glass-*`, `--grad-accent`/`--grad-surface`/`--grad-page`, `--r-1..3`,
  `--shadow-glass`, `--t-fast/base/slow`, `--sidebar-w`, `--content-max`, `--content-pad`.
- **Desktop multi-column grids** — deal/alert/browse lists lay out in 2–3 columns ≥1024px; the
  portfolio table widens; the mobile stacked-card layout (≤639px) is untouched.

**Do-not-break contract held** — every class name, `input[name]`, `aria-label`, button accessible
name, `data-label`, and honest-empty-state string the 126 tests query was preserved. Motion wraps
existing elements (a `motion.button` renders `<button>`; `motion.ul` renders `<ul class="…">`), and
all CSS is additive — no existing rule renamed or removed (the three `@keyframes` + their
reduced-motion guards kept). The one structural change (sidebar vs bottom-nav) is JS-gated so only
one nav is ever mounted.

**Sacred constraints held** — frontend-only by construction: no backend, no `data/`, no price
resolution, no snapshots, no schema. 105-scan baseline 0 regressions.

## 18. Living UI — Dashboard + command palette + toasts + polish (2026-08-20)

A "Living UI" phase on top of §17, making the app feel alive and interactive
([plan](docs/superpowers/plans/2026-08-20-living-ui.md)). Frontend-only; backend, `data/`, and the
105-scan baseline untouched. **146 frontend tests green (126 prior + 20 new); build clean.**
Executed via subagent-driven-development (one fresh implementer per task, continuous execution).

- **Dashboard (Home) landing tab** — `frontend/src/components/Dashboard.tsx` is now the default
  landing surface (default view changed `alerts`→`home`). It reads `GET /collection/portfolio` once
  on mount and renders animated count-up KPIs (market value, cost basis, unrealized P/L, priced/
  unpriced), an allocation donut (inline SVG, `frontend/src/components/viz.tsx`), a movers bar viz
  (top gainers/losers), and quick-action CTAs. **Honest-empty** when no holdings or the fetch fails
  — never `$0`, never fabricated. `frontend/src/lib/useCountUp.ts` (rAF, reduced-motion-gated,
  jsdom-safe: no-rAF/reduced/non-positive → target instantly) + `frontend/src/components/Reveal.tsx`
  (scroll-reveal, `useReducedMotion`-gated) + `frontend/src/lib/useReducedMotionSafe.ts` (normalizes
  framer's `boolean|null` to `boolean`). Added a 9th **Home** nav tab (first in both the mobile
  bottom-nav and the desktop sidebar) with a new `HomeGlyph`.
  **Default-view safety (the critical invariant):** `BulkScan.test.tsx` is the only test rendering
  real `<App/>`; its fetch stub returns `200 {}` for any `/collection` URL, so `getPortfolio()` resolves
  to `{}` (no throw). Dashboard null-guards `summary` (`p?.summary ?? null`, `summary?.field ?? 0`)
  and try/catches the fetch (`.catch(() => setSummary(null))`, `cancelled` flag) → the `{}` response
  renders the empty state, never crashes, never throws to an unmounted component. Dashboard's CTA
  buttons use DISTINCT verb-phrase accessible names (`"Start scanning"`, `"Browse the catalog"`,
  `"Snipe deals"`, `"Open ledger"`, `"Watch a card"`) — never an exact nav-tab name — so BulkScan's
  `getByRole("button", { name: "Scan" })` (line 165, fired immediately after render while Home is
  mounted) still resolves to exactly one button. Dashboard renders no `<input type="file">`.
- **Command palette + keyboard shortcuts** — `frontend/src/components/CommandPalette.tsx` is a
  Cmd/Ctrl+K overlay (AnimatePresence; renders **nothing when closed**, so it adds no buttons to the
  DOM that could collide with test queries). Nav commands (jump to any of the 9 tabs) + debounced
  card search reusing `searchCards` → opens card detail. AppShell adds a keydown listener: Cmd/Ctrl+K
  toggles, `1`–`9` jump tabs, Escape closes — **ignored when focus is in an input/textarea/select/
  contenteditable** (typing in a search box never jumps tabs). A `"Search"` header trigger button
  (`⌘K`) is added; its name is distinct from nav names (nav uses "Browse", not "Search").
- **Toast notifications** — `frontend/src/components/Toast.tsx`: `ToastProvider` + `useToast` +
  `ToastContext`. **The context default is a noop** `{ toast: () => {} }`, so `useToast()` never
  throws without a provider. `<ToastProvider>` is wired in `main.tsx` (production) only. **Every
  existing test renders `<App/>` or a component directly (no provider) → `useToast()` returns the
  noop → ZERO toasts render → zero collision with any text/button query.** Toasts render via
  `createPortal(..., document.body)` (pure-text: icon + message + close X, NO action buttons) so
  `container.*`-scoped tests don't see them. Wired to: App `handleConfirm` + `handleBulkAddAll`
  ("Added to collection" / "Added N cards"), AppShell watch `onCreated` ("Watch created"),
  SealedLedger log/refresh/sync ("Purchase logged" / "Valuations refreshed" / "eBay key missing —
  valuations skipped" / "Sheet synced" / "Sheets not configured"). Toast copy never contains
  `"Charizard"` / `"no card found"` / `"$0.00"` / any exact nav name.
- **Global polish** — additive CSS in `frontend/src/styles.css`: an animated gradient mesh
  `body::before` (slow drift, reduced-motion → static), Dashboard KPI/donut/movers styles (KPI grid
  `auto-fit`, dashboard-grid 1-col → 2-col ≥880px), command-palette styles (`min(640px,92vw)`),
  toast styles (`min(360px,92vw)`), `:focus-visible` rings, a once-on-mount view-transition shimmer
  on `.app-content::after`. All new selectors; no existing rule renamed/removed.

**Do-not-break contract held** — the 9 nav accessible names, every frozen class/`input[name]`/
`aria-label`/button-name/`data-label`/empty-state string, and the `getByRole("button",{name:"Scan"})`
one-element invariant all preserved. The default-view change is safe by construction (null-guard +
try/catch + distinct CTA names). The toast system is safe by construction (default-noop context →
zero toasts in tests). New tokens referenced: `--font-mono` (palette trigger), `--warn` (#d29922).
Two jsdom test adaptations: a `beforeAll` `IntersectionObserver` no-op stub (framer `whileInView` in
`Reveal` needs it) in `Dashboard.test.tsx`; fake-timer `useRealTimers` before `waitFor` in
`Toast.test.tsx`.

**Sacred constraints held** — frontend-only: no backend, no `data/`, no price resolution, no
snapshots, no schema. 105-scan baseline 0 regressions; 568 backend tests untouched.
