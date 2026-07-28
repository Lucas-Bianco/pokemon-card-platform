# Design: Pokémon Card Recognition Platform — Phase 0 + Phase 1

**Date:** 2026-07-28
**Owner:** Lucas
**Status:** Approved design — ready for implementation planning
**Scope:** Phase 0 (foundation) and Phase 1 (single-card scan). Later phases are described only
enough to justify architectural choices made now.

---

## 1. Overview

A responsive web app (PWA, installable on phone and desktop) that identifies a Pokémon card from a
photograph and tracks it in a collection with live valuation.

This is Phase 0+1 of a **single phased platform**, not a standalone app. Six further phases
(portfolio tracking, grade prediction, bulk cataloging, deal sniping and sealed EV, set-completion
optimization, counterfeit detection) are planned on top of the same foundation — see the roadmap in
section 7. The foundation is therefore designed to serve them, not just the immediate scan feature.

### Goals

- Photograph a raw Pokémon card and get a confident, correct identification.
- Know when identification is uncertain, and degrade gracefully instead of guessing.
- Store identified cards in a collection with current market value.
- Work on a phone camera and a desktop browser from one codebase.

### Non-goals (this phase)

- Grading, counterfeit detection, multi-card detection, deal alerts, set optimization. These are
  later phases.
- User accounts / multi-tenancy. Single-user local-first is sufficient for Phase 1.
- Fine-tuning a custom embedding model. Pretrained encoders are the Phase 1 baseline.

### Guiding principle

The most accurate recognition system is a **hybrid** of visual matching and OCR. The two approaches
fail on *different* inputs — embeddings struggle to separate near-identical reprints and holo
variants; OCR struggles with glare, blur, and angle. Fusing two independent signals means their
errors do not correlate, and the system can report calibrated uncertainty rather than a confident
wrong answer.

---

## 2. Recognition pipeline

Five stages take a photo to a confident card identity.

### 2.1 Detect & rectify (client, WebAssembly)

Locate the card's four corners in the frame and perspective-warp it to a canonical flat rectangle
(portrait, fixed dimensions, e.g. 600×825).

Runs client-side in OpenCV.js so it can drive a **live camera overlay** that highlights the detected
card in real time — the user sees whether the shot is good before capturing. A server round-trip per
frame would make this feel broken.

Rectification is the highest-leverage stage in the system:

- Both downstream engines receive a consistent, angle-corrected input instead of a skewed snapshot.
- Network payload drops from a multi-megabyte phone photo to a small normalized crop.
- **Phase 3 (Grade Predictor) requires exactly this geometrically-normalized image** to measure
  centering and inspect corners. Phase 1 builds Phase 3's input.

Fallback: if automatic corner detection fails, the user can drag the four corners manually.

### 2.2 Visual embedding match (server)

Embed the rectified crop with a pretrained vision encoder and run nearest-neighbour search against
pre-computed embeddings for every card in the catalog. Returns **top-K candidates with similarity
scores** — never a single unqualified guess.

### 2.3 OCR verification (server)

Run OCR on high-signal regions of the same rectified crop:

- **Collector number** (e.g. `032/078`) — combined with set, this is a *unique key* for a card and
  therefore an extremely strong independent signal.
- **Card name** — secondary confirmation.
- **Set symbol region** — supports set disambiguation.

Because the input is rectified, these regions sit at predictable coordinates, which makes targeted
region OCR far more reliable than running OCR over the whole raw photo.

### 2.4 Fusion & calibrated confidence

Combine visual similarity and OCR agreement into a single calibrated confidence score.

| Condition | Behaviour |
|---|---|
| Both signals agree, high score | Auto-confirm, return the card |
| Signals disagree, or score below threshold | Return **top 3** for the user to choose |
| No plausible candidate | Report failure, offer manual search |

User selections in the ambiguous case are **logged as labelled training data**, which becomes the
dataset for fine-tuning the encoder in a later phase. The product improves through use.

This stage is what separates a product from a demo: the system must know when it is unsure.

### 2.5 Variant disambiguation

The hardest correctness problem in Phase 1. Holo, reverse-holo, and non-holo printings frequently
share identical artwork — near-indistinguishable to an embedding model — but differ substantially in
price. Misidentifying a variant produces a wrong valuation, which corrupts the collection and every
downstream module.

Handled by:

- **Specular/glare analysis** on the rectified image — holo and reverse-holo foiling produce
  characteristic highlight distributions across different regions (art box vs. card body).
- **Targeted user prompt** when the signal is inconclusive. An explicit two-tap question is better
  than a silent wrong answer.

---

## 3. Data layer

Three stores, each with a distinct responsibility.

### 3.1 Card catalog

Every Pokémon card: set, collector number, rarity, variants, and the official card image.

Primary source: **`pokemontcg.io`** — metadata, images, and embedded market pricing in one API,
approximately 20k cards.

> **Open item for planning:** verify current pricing coverage, rate limits, licensing, and API-key
> requirements before committing to it as the sole source. This is the project's one significant
> external dependency and should be pinned down first.

Data is **mirrored into local Postgres** rather than queried live, because:

- The embedding build job needs bulk offline access to every card image.
- Recognition must not depend on third-party uptime or rate limits.

A scheduled sync job pulls newly released sets.

### 3.2 Reference embedding index

The core of recognition. An offline job (one-time, then incremental per new set):

1. Take each catalog card image.
2. Apply **the same rectification treatment** user photos receive, so reference and query images are
   directly comparable.
3. **Augment** — glare, blur, slight rotation, colour shift — so the index reflects what a real phone
   photo looks like rather than a pristine scan.
4. Embed and store the vector.

At ~20–60k vectors, this is small by vector-search standards: **exact brute-force search is
millisecond-fast**, so no approximate-index tuning is required. This removes an entire category of
complexity from Phase 1.

Adding a new set is cheap: sync catalog → embed new cards → done.

### 3.3 Price history

Prices are **snapshotted over time**, not merely read as a current value.

- Enables true portfolio P/L in Phase 2.
- Provides the historical baseline the Phase 5 deal sniper needs to detect underpriced listings.

Prices are cached and refreshed on a schedule. A card's displayed value never blocks on a live API
call.

### 3.4 Data-layer principle

**The app never depends on an external service being available at scan time.** Catalog, embeddings,
and prices are all local and refreshed in the background. Recognition remains fast and functional
when an upstream API is down or throttling.

---

## 4. Application architecture

Split by ecosystem strength: each half is written in the language that is genuinely good at its job.

### 4.1 Frontend — React + TypeScript, PWA

Responsibilities: camera capture, live detection overlay, client-side rectification (OpenCV.js /
WASM), collection browsing, installable home-screen experience on phone and desktop.

### 4.2 Backend — Python + FastAPI

**Rationale (deliberate, load-bearing decision):** the entire computer-vision and ML ecosystem is
first-class in Python and second-class or absent in JavaScript. Phase 3 (grading model), Phase 4
(object detection), and Phase 7 (counterfeit analysis) all require it. Choosing Python now avoids a
wall three phases in.

**Accepted tradeoff:** two languages means two development environments and a deployment story that
includes a Python service. This cost is accepted deliberately; the alternative is fighting the ML
ecosystem for the life of the project.

### 4.3 Component choices

| Concern | Choice | Note |
|---|---|---|
| Embeddings | Pretrained vision encoder (CLIP / DINOv2) | Already strong at near-duplicate retrieval; no training needed in Phase 1 |
| Vector search | FAISS | Exact search is sufficient at this scale |
| OCR | PaddleOCR | Handles real-world glare and angle better than Tesseract |
| Database | Postgres | Catalog, collection, price history |
| Client CV | OpenCV.js (WASM) | Live overlay requires on-device execution |

### 4.4 End-to-end flow

```
camera
  → live detect + rectify        (browser / WASM)
  → POST rectified crop
  → embed + FAISS top-K   ┐
                          ├─ in parallel (server)
  → targeted region OCR   ┘
  → fuse into calibrated confidence
  → high confidence: return card
    low confidence:  return top-3 for user selection
  → save to collection with current price
```

---

## 5. Error handling

| Failure | Handling |
|---|---|
| Card not detected in frame | Live overlay shows no lock; user may place corners manually |
| Blurred / low-light capture | Client-side quality gate warns before upload |
| OCR unreadable | Fall back to visual-only match, lower confidence, likely top-3 prompt |
| Visual match ambiguous | OCR arbitrates; if still ambiguous, top-3 prompt |
| Variant indeterminate | Explicit user prompt (holo / reverse / non-holo) |
| Card absent from catalog | Report clearly; queue for catalog sync review |
| Upstream API down | Serve cached catalog and prices; scanning unaffected |
| Price data stale | Display value with an explicit "as of" timestamp |

---

## 6. Testing strategy

- **Rectification** — fixture photos at varied angles, distances, and lighting; assert output
  geometry is within tolerance of the canonical rectangle.
- **Recognition accuracy** — a held-out labelled set of real phone photos, measuring top-1 and top-3
  accuracy. This is the project's headline metric and must be tracked from the start.
- **Confidence calibration** — verify that low-confidence results actually correlate with errors.
  A confidence score that does not predict correctness is worse than none.
- **Variant handling** — dedicated fixtures for holo / reverse-holo / non-holo of the same card.
- **Data layer** — sync job idempotency; embedding job incrementality; price snapshot correctness.
- **Degradation** — recognition still succeeds with the upstream API unreachable.

---

## 7. Phase roadmap (context only)

| Phase | Module | Depends on |
|---|---|---|
| 0 | Foundation: catalog, pricing, collection store | — |
| 1 | Single-card scan (**this spec**) | 0 |
| 2 | Portfolio tracker: cost basis, P/L, charts | 0, 1 |
| 3 | Grade Predictor: CV grading + grading EV | 1 (rectification) |
| 4 | Bulk cataloger: many cards per photo | 1 |
| 5 | Deal sniper + sealed EV | 0 (price history) |
| 6 | Set-completion optimizer | 0 |
| 7 | Counterfeit detector | 1 |

Each phase ships independently usable functionality and receives its own spec and implementation
plan.

---

## 8. Open items for planning

1. Verify `pokemontcg.io` pricing coverage, rate limits, licensing, and API-key requirements.
   Identify a fallback or supplementary price source if coverage is insufficient.
2. Select the specific pretrained encoder and confirm its near-duplicate retrieval accuracy on a
   sample of real card photos before building the full index.
3. Determine deployment target for the Python service (local-first for Phase 1 is acceptable).
4. Define the initial confidence threshold empirically from the labelled evaluation set rather than
   guessing a constant.
