# AI_CONTEXT.md — bring any AI model up to speed on this project

> **Purpose:** this is the single file to hand an AI assistant so it understands what this project
> is, what has been built, what has been *measured*, and what not to break. Read it top to bottom
> before proposing anything.
>
> **Keep it current.** Update this file after any change that alters architecture, measured
> results, or the roadmap. A stale onboarding doc is worse than none, because it is trusted.
>
> Last updated: **2026-07-31**

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
| 2 | Portfolio tracker: cost basis, P/L, charts | ⛔ Blocked on data — see §6 |
| 3 | Grade predictor: CV grading + grading EV | Planned |
| 4 | Bulk cataloger: many cards per photo | Planned |
| 5 | Deal sniper + sealed EV | Planned |
| 6 | Set-completion optimizer | Planned |
| 7 | Counterfeit detector | Planned |

**Tests:** 207 backend (pytest) + 22 frontend (vitest).

### Measured recognition performance — on real phone photos of physical cards

This is the number that matters. Everything before Phase 1b was measured on *degraded reference
images*, which flattered it badly.

| | value |
|---|---|
| **Precision when the pipeline commits** | **100%** (29/29, zero confident errors) |
| **Coverage** (scans producing a confident answer) | **64%** (was 31% before Phase 1c) |
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
  prices/            provider.py (protocol), pokemontcg.py, service.py
  collection/        store.py — add/remove/list/valuation
  recognition/       detectors.py, rectify.py, encoder.py, index.py, ocr.py, fusion.py, service.py
  scans/             store.py — logs every scan as ground truth
  api.py             FastAPI, cli.py  CLI
backend/scripts/     evaluate_recognition.py, evaluate_detection.py, spot_check.py
frontend/src/        api/, lib/, components/  (CameraCapture, ScanResult, CandidatePicker,
                     PriceLine, CornerAdjust)
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

**Phase 2 (portfolio tracker) is blocked on DATA, not code.** Measured 2026-07-30:
- 0 of 37 collection items had a cost basis → P/L would report 100% profit on everything
- 0 price series had more than one date → every chart would be a single dot

Both causes are now fixed — the scan flow asks "what you paid" (optional), and
`refresh-collection-prices` accrues history. **Phase 2 needs a few weeks of scheduled runs before it
can chart anything real.** Building it sooner means charting single dots.

---

## 7. The most useful next levers

1. **Rectification vertical alignment — the real remaining OCR blocker.** OCR was improved on
   2026-07-31 (see below), but diagnosis of the residual failures showed the crop itself is often
   at fault: several rectified cards put the *weakness / resistance / retreat* row inside the bottom
   12% strip, meaning the detected quad extends below the card and the whole card content sits too
   high. That is a detector-precision problem, not an OCR one, and no amount of preprocessing fixes
   it. Fixing the quad would help both OCR and the embedding.
2. **Phase 3 (grade predictor).** Needs the rectified card images the pipeline now produces reliably.
   The hard part is training data: graded cards with known PSA/CGC grades.
3. **Phase 2**, once price history has accrued — see §6.

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

Result: 24 → **27 correct** reads, wrong held at 4. Rejected after measurement: an `S`→`5`
confusion repair, which added 2 wrong reads for 0 correct, and allowing bare numbers in the wide
band, which doubled wrong reads from 4 to 8.

End-to-end that was worth **+1 confident answer** (63% → 64% coverage, 0 regressions) — OCR only
arbitrates when its reading uniquely matches one shortlisted candidate, so extra correct reads do
not convert one-for-one.

*Done 2026-07-30: the PWA now has a collection view. It shows holdings and a valuation summary, and
renders unrealised P/L as an em dash when no cost basis exists rather than reporting market value as
pure profit.*

---

## 8. Working agreements

- **Score every recognition or detection change with `backend/scripts/evaluate_detection.py`.** It
  replays the real scans and fails on a single regression. A confidently wrong card is worse than a
  missed detection.
- **Ask before destructive commands.** In particular, never delete anything under `data/` — it holds
  20,391 downloaded images, a 40 MB index, the database, and 101 irreplaceable real scan photos.
- Match the style of surrounding code.
- `CLAUDE.md` holds the same conventions in condensed form for Claude Code specifically.
