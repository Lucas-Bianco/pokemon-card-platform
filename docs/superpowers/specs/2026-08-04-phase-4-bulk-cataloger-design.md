# Phase 4 — Bulk Cataloger (Design)

> **Status:** Design. Auto mode — surfaced for visibility, not blocking on approval.
> **Date:** 2026-08-04
> **Repo:** `C:\ClaudeKnowledge` (github.com/Lucas-Bianco/pokemon-card-platform)
> **Predecessor:** Phase 05b (deal alerts + eBay sold-comps evidence) shipped 2026-08-04. 485 backend + 102 frontend tests green. This phase is additive to the single-card recognition pipeline.

## Goal

Detect, recognize, and value **every card in one binder-page photo** in a single scan. One photo → N
identified + valued cards, one `scan_logs` row per card (grouped by a shared `batch_id`), with a batch
review grid where each card can be fixed up independently (corner drag, candidate pick, per-card
variant) and optionally bulk-added to the collection.

Today the pipeline finds **one** card per photo: `detect_candidates()` returns at most one quad per
strategy, recognition keeps the best-scoring crop, and OCR runs once on the winner. Phase 4 splits
**detection** (run once → N non-overlapping quads) from **recognition** (run per-quad, batched), so a
binder page becomes N independent cards each carrying its own `status`/`price`/`rectified_path`.

## Standing directive & sacred constraints (in force)

- Auto mode — proceed autonomously, no per-step check-ins. Only edit/delete files inside `C:\ClaudeKnowledge`. **Commit all new code to GitHub** (push `origin/main`; solo repo). Ask before destructive/irreversible commands. Never delete anything under `data/` (20,391 images, 40 MB FAISS index, SQLite db, 105 irreplaceable real scans).
- Python 3.12 **only** via `backend/.venv` (system Python is 3.14, lacks ML wheels).
- **Never resolve "the latest price" ad-hoc** — only `PriceService.latest_price(card_id, variant)`. Honest empty states — `None`/em dash, never `$0`, never fabricate. Snapshots immutable.
- **The phase is additive:** no regression to single-card recognition. `evaluate_detection.py` against the 105-scan baseline must stay green. The single-card `POST /recognize` + `detect_candidates` path is unchanged.
- **Recognition is the arbiter, not geometry.** A card-shaped sleeve/glare slot still embeds to a low `visual_score` and must NOT be auto-promoted on geometry alone. The `-inf` best-score floor and the "found a card-shaped quad != found the card" invariant are preserved per crop.
- Match surrounding code style; keep `AI_CONTEXT.md` current. Reuse `CardEncoder.embed_many`, `rectify_from_corners`, `_fuse_for`, `CandidatePicker`, `CornerAdjust`, `ScanResult`, `CollectionStore.add` rather than duplicating.

## Open questions — resolved defaults (auto mode)

The parallel design map surfaced 9 open questions; resolved here with reasoned defaults:

1. **Binder-page fixtures + ground truth** — we do not have reviewed multi-card photos. **Decision:** ship a **synthetic multi-card fixture generator** (compose N catalog crops onto a page-sized canvas) for automated regression tests; document real-binder capture as a follow-up. We cannot claim real-photo coverage without real fixtures — the synthetic path gives ground truth for the pipeline without overclaiming.
2. **Detector strategy** — line/segment grid detection vs retuned adaptive_rect. **Decision:** extend the existing `canny` + `otsu_rect` strategies to collect **all** card-shaped contours (both Otsu polarities) + IoU NMS. Defer the line/segment grid strategy as a measured follow-up if synthetic fixtures show the blob approach underperforms. Lowest-risk, additive.
3. **OCR parallelism budget** — **Decision:** configurable `batch_ocr_workers` setting, default `2`, clamped to `[1, 4]`. A `ThreadPoolExecutor` with one RapidOCR engine per worker (the engine is not thread-safe). OCR at ~1 s/crop dominates batch latency; 2 workers halves a 9-card page to ~5 s.
4. **`image_path` semantics for batch rows** — **Decision:** all N rows share the source photo (written once); per-card crops are already persisted as `rectified_path`. Simplest, matches "one photo → N cards".
5. **Batch size cap** — **Decision:** `max_cards` query param, default `9` (a 9-pocket page), clamped to `[1, 18]` in the endpoint. Detection may return more; the endpoint caps N before recognition.
6. **Per-card variant** — **Decision:** default `normal` (matches the current single-card hardcoded `VARIANT="normal"`), but expose a **per-cell variant selector** in the review grid so reverse/holofoil cards can be corrected before bulk-add. Price is resolved per card with that cell's variant.
7. **Bulk-add provenance** — **Decision:** reuse `CollectionStore.add`'s merge-to-one-row behavior (duplicate `(card_id, variant)` tops up quantity). The per-lot cost-basis model is an explicitly deferred Phase 2 follow-up; bulk cataloging is "what do I own", not "what did each purchase cost".
8. **Batch UI entry point** — **Decision:** in-pane **mode toggle** in the Scan pane (single-card ↔ bulk), not a 7th bottom-nav tab (avoids 6-item overflow on narrow phones).
9. **Commit strategy for batch logging** — **Decision:** per-crop commit (durable audit trail; matches the existing single-row durable commit). A mid-batch failure keeps the rows already logged.

## Architecture

Split detection from recognition; additive schema; new batch endpoint; batch review grid.

```
binder-page photo (one UploadFile)
   ↓
detect_all_quads(image)        NEW — collect ALL card-shaped contours from canny + otsu_rect
   ↓                            (both Otsu polarities), IoU NMS over the union → N quads
recognize_many(image, quads)    NEW — rectify each, embed_many ONCE, index.search per vector,
   ↓                            _fuse_for + reader.read per winning crop (parallel OCR pool)
N × RecognitionResult            each independently confident|ambiguous|not_found, each with
   ↓                            its own rectified_path. Recognition is the arbiter (no geometry auto-promote).
POST /recognize/batch           NEW — resolves price per confident card via latest_price,
   ↓                            returns BatchRecognizeOut{batch_id, results: [RecognizeOut]}
POST /scans (per card)           EXISTING, extended — threads batch_id + batch_index per row
   ↓
batch review grid (PWA)         NEW mode — N ScanResult cells, per-cell fix-ups, bulk-add
```

## Components

### 1. Multi-quad detection + IoU NMS — `recognition/detectors.py`

Add `detect_all_quads(image) -> list[tuple[str, np.ndarray]]` alongside `detect_candidates` (the single-card path stays unchanged):

- Generalize `_largest_rotated_rect` and `_largest_polygon_quad` into **all-variants** that **collect** every contour passing `quad_is_card_shaped` instead of returning the first. The existing `MIN_AREA_FRACTION=0.05` already admits a binder card (~0.11 of a 9-card frame); `MAX_AREA_FRACTION=0.98` already rejects whole-frame blobs. **Do not lower/remove `MAX_AREA_FRACTION`** — that guard exists because adaptive thresholding merged card+background into a whole-frame blob on 101/101 real scans; per-region gating is not required because the global gate already handles the degenerate case for a grid of ~0.11-area cards.
- `detect_otsu_rect` already tries both polarities but returns the first hit — collect from **both** polarities.
- **IoU-based NMS** over the union of all strategy/polarity quads: compute polygon intersection via `cv2.intersectConvexConvex` (or the rotated-rect intersection helper), drop the smaller/lower-area quad of any pair above an IoU threshold (default `0.3`). No NMS exists anywhere in the repo today; without it a 9-card page × 2 strategies × 2 polarities can yield ~36 overlapping quads and the same card reported twice. Recognition-as-arbiter still applies post-NMS (a kept quad that embeds low is a `not_found`, never auto-promoted).
- A new `_iou(a, b) -> float` helper and `_nms(quads, threshold) -> list` helper.

### 2. Batched recognition — `recognition/service.py`

Add `RecognitionService.recognize_many(image, quads) -> list[tuple[np.ndarray, RecognitionResult, CenteringResult | None]]`:

- Rectify each quad via `rectify_from_corners` (already per-quad; re-orders corners internally — harmless).
- `vectors = self.encoder.embed_many(crops)` **once** (encoder.py:43 already supports `batch_size=128`; `embed()` delegates to it). Visual embedding is 2.2 ms — the win is GPU-dispatch amortization.
- `index.search(vector, top_k=visual_top_k)` per vector (trivial loop).
- `_fuse_for(crop, found)` per crop — this runs OCR (`reader.read`, ~1 s) + fusion + rectified-crop persistence per crop. The current "OCR once on the winner" rule is **inverted** for batch (every slot is a card). The asymmetric OCR-trust rule in `fusion.py` is preserved per crop (full N/M can promote; bare only confirms).
- **Parallel OCR:** wrap the per-crop `_fuse_for` OCR step in a `ThreadPoolExecutor(max_workers=settings.batch_ocr_workers)`, with one `CollectorNumberReader` instance per worker (RapidOCR is not thread-safe). The existing `self.reader` is the template; each worker deep-copies/constructs its own. Preserve the stale-index guard and the `not_found → rectified_path=None` contract per crop. `_persist_rectified_crop` runs per crop, fail-soft.
- `config.py`: add `batch_ocr_workers: int = 2` (env `CARDPLATFORM_BATCH_OCR_WORKERS`), validated to `[1, 4]`.

### 3. Batch scan logging — `db/models.py`, `db/migrations.py`, `scans/store.py`

- `ScanLog` gains nullable `batch_id: Mapped[str | None]` (indexed) + `batch_index: Mapped[int | None]`. Add to **both** the model and `_ADDITIVE_COLUMNS` in the same change (schema drift between them 500s on first batch insert). Append:
  ```python
  ("scan_logs", "batch_id", "VARCHAR"),
  ("scan_logs", "batch_index", "INTEGER"),
  ```
  The 105 sacred rows stay NULL; `NULL batch_id` is treated as a singleton batch everywhere.
- `ScanStore.record_batch(image_bytes, batch_id, results)` — writes the source photo **once** (all rows share `image_path`), then inserts N `ScanLog` rows each with its own `predicted_card_id`/`status`/`confidence`/`visual_margin`/`collector_number_read`/`rectified_path`/`variant`/`batch_index`, **committing per row** (durable). Logs every card including `not_found` (most valuable ground truth).
- `ScanStore.accuracy()` becomes **batch-aware**: count one representative row per `batch_id` (the first by `id`) so N rows per photo don't inflate the 105-scan baseline. Rows with `NULL batch_id` count as singleton batches (one each) — preserves the existing baseline. Add a `batches` count to `ScanAccuracy` for transparency.

### 4. Batch endpoint + wire types — `api.py`, `frontend/src/api/`

- `POST /recognize/batch` alongside `POST /recognize` (api.py:706):
  - Request: multipart `file` + query `variant` (default `normal`, applied per card) + `max_cards` (default `9`, clamped `[1, 18]`).
  - Runs `detect_all_quads(image)` → cap to `max_cards` (largest-area first) → `service.recognize_many(image, quads)`.
  - Resolves price per confident card via `PriceService(session).latest_price(card.id, variant)`; `None` for ambiguous/not_found (never `$0`, via the existing `_price_out`/`_price_response` contract). Each result carries its own `rectified_path`.
  - Returns `BatchRecognizeOut{batch_id: str, count: int, results: list[RecognizeOut]}` — `batch_id` is a `uuid4` so the N results are grouped. **Never collapses per-card statuses into one batch status** (that would fabricate confidence).
  - Does NOT write `ScanLog` (preserves the recognize/log separation); the client logs per card via the existing `POST /scans`, threading `batch_id` + `batch_index` + `rectified_path` + `variant`.
- `frontend/src/api/types.ts`: `BatchRecognizeResponse { batch_id: string; count: number; results: RecognizeOut[] }`.
- `frontend/src/api/client.ts`: `batchRecognize(file, variant?, maxCards?)` mirroring `recognize()` (stays under `/api` for the Vite proxy + HTTPS). The `recordScan` client call gains optional `batch_id` + `batch_index` + `rectified_path` params (it currently drops `rectified_path`/`variant`).

### 5. Batch review grid — `frontend/src/components/`

- A **mode toggle** in the Scan pane (single-card ↔ bulk), not a 7th nav tab. Capture reuses `CameraCapture` for one binder-page photo; a file-upload fallback handles multi-photo batches.
- State generalizes `runRecognition` to arrays: `results[]` + `scanIds[]` paired per card, with per-cell state hooks so `ScanResult`/`CornerAdjust` props stay unchanged.
- Review renders a CSS grid of N `ScanResult` cells, each branching on its own status exactly as today: confident → confirm, ambiguous → `CandidatePicker` (reused per cell), not_found/ambiguous → `CornerAdjust` per cell (each holds its own Blob; `onSubmit` converts display-fraction corners to source pixels and re-runs a per-cell `recognize` with `corners=`).
- **Per-cell variant selector** (default `normal`) — corrects reverse/holofoil before bulk-add; price resolves with that variant.
- Lazy-load per-cell price/grading enrichment on focus, not on grid render (avoid rate-limiting on 50+ cards).
- **Bulk-add to collection** via the existing `POST /collection` per distinct `(card_id, variant)` (let the store merge duplicates into one topped-up row; never fabricate `$0` — `formatMoney` returns `—` for `None`). Surface per-cell logging status; suppress the watch-nudge in bulk mode.

### 6. Eval harness — `backend/scripts/evaluate_detection.py`

- Extend to score multi-card fixtures with **per-card ground truth** (a binder page has N truths). Keep the "one confident regression fails the run" rule, applied **per card**. Ensure single-card coverage stays green (the phase is additive — the 105-scan baseline must not regress).
- A reviewed **synthetic** binder fixture set (generated by a small `backend/scripts/make_batch_fixtures.py` composing N catalog crops onto a page canvas) provides ground truth for automated tests. Real-binder capture is a documented follow-up.

## Verification (end-to-end)

- **Backend:** `backend/.venv/Scripts/python -m pytest` — 485 → N, all green. New tests: `detect_all_quads` collects N quads from a synthetic page, IoU NMS dedupes overlaps, both Otsu polarities contribute, `MAX_AREA_FRACTION` still rejects whole-frame blobs; `recognize_many` rectifies+embeds+fuses per crop, parallel OCR pool, per-crop `not_found`/`rectified_path` contract, recognition-as-arbiter (low-visual-score kept quads stay `not_found`); `ScanStore.record_batch` writes one photo + N rows + per-crop commit; `accuracy()` batch-aware (N rows per batch count once); `POST /recognize/batch` returns N `RecognizeOut` + honest `None` prices; `evaluate_detection.py` 105-scan baseline unchanged.
- **Frontend:** `npm --prefix frontend test -- --run` — 102 → N green; `npm --prefix frontend run build` clean. Manual smoke (backend :8000, frontend :5173): bulk mode → capture/upload a binder page → grid of N cards each with its own status/price/fix-ups; per-cell corner drag re-runs recognition; bulk-add tops up the collection.
- **Sacred constraints:** no ad-hoc price resolution (only `latest_price`); honest empty states (no `$0`, never a fabricated card or status); snapshots immutable; no `data/` deletion; additive schema only (no destructive migration, 105 rows stay NULL); `func.lower(...).like` for text search; single-card path unchanged.

## Out of scope

- Line/segment grid detection strategy (a measured follow-up if blob+NMS underperforms on real binder photos).
- Real-binder fixture capture (synthetic fixtures only this phase).
- Per-lot cost-basis model (still deferred from Phase 2; bulk-add merges duplicates).
- Persisting a parent batch row (the shared `batch_id` + `batch_index` on each `scan_logs` row is sufficient grouping).
- Auto-rotating/flattening the binder page (assume the photo is oriented like the cards).

## Execution

Subagent-driven (fresh implementer per task, TDD, inline spec + quality reviews to conserve budget — the established Phase 05/05b pattern). 7 tasks: detection → recognize_many → batch scan logging → batch endpoint → batch UI → eval harness → docs/integrate/verify/push/deploy. Auto mode: proceed through all tasks without per-step check-ins; commit per task; push + deploy at the end.