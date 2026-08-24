# CLAUDE.md

This file gives Claude Code guidance when working in this repository.

## Project overview

<!-- One or two sentences: what this project is and what it does. -->
A local-first Pokemon trading card recognition and valuation platform. Phase 0 is the data foundation: catalog, pricing, collection store.

**Layout (since 2026-08-22).** This repo lives at `C:\ClaudeKnowledge\Pokemon Project\v0.1\`. A completed phase bumps the version into a sibling folder (`v0.2`, ...). The 3.4 GB data store is deliberately OUTSIDE the version folder at `C:\ClaudeKnowledge\Pokemon Project\data\` so a version bump never duplicates it; `CARDPLATFORM_DATA_DIR` in `.env` points there. The repo's own `data/` holds only the 4 tracked batch fixtures.

## Setup

<!-- How to get the project running from a fresh clone. -->
```sh
# install dependencies
C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\Pokemon Project\v0.1\backend[dev,ml]"
```

## Commands

<!-- The commands you run most often. Keep these accurate — Claude will trust them. -->
- Build: no build step configured yet.
- Test: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\python.exe -m pytest` (run from repo root)
- Lint / format: no lint/format step configured yet.
- Run / dev server: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --reload --port 8000`
- Coverage: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\python.exe -m pytest --cov=cardplatform --cov-report=term-missing`
- Sync the card catalog: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\cardplatform.exe sync-catalog` (idempotent, resumable)
- Fetch prices: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\cardplatform.exe refresh-prices base1-4 hgss4-1`
- Accrue price history: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\cardplatform.exe refresh-collection-prices` (run on a schedule; Phase 2 charts need repeated runs)
- Build the recognition index: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\cardplatform.exe build-index` (downloads ~20k images; re-runs skip cached)
- Evaluate recognition accuracy: `C:\ClaudeKnowledge\Pokemon Project\v0.1\backend\.venv\Scripts\python.exe backend/scripts/evaluate_recognition.py --sample 500`

## Project structure

<!-- Key directories and what lives in them. -->
- `.claude/` — Claude Code configuration (settings, commands, agents, skills).
- `backend/` — the `cardplatform` Python package (source in `backend/src/cardplatform/`, tests in `backend/tests/`).

## Conventions

<!-- Coding style, naming, patterns to follow or avoid. -->
- **Python 3.12 only.** System Python is 3.14 and lacks wheels the CV/ML phases need. Always use `backend/.venv`.
- **Never resolve "the latest price" ad hoc.** Call `PriceService.latest_price(card_id, variant)`. tcgplayer prices per variant (`holofoil`, `normal`, …) while cardmarket publishes one `"aggregate"` row per card, so a naive `variant`-filtered query silently values cardmarket-only cards at $0.
- **Always surface price staleness.** Return `source` and `source_updated_at` with any price. Real example: cardmarket said $1531 while tcgplayer said $800 for the same card on the same day. Never blend sources into one number.
- **Price snapshots are immutable.** Insert new rows; never update. History is what Phase 2 charts and Phase 5 uses to spot underpriced listings.
- **Valuation is conservative.** An unpriced item contributes 0 and is counted in `unpriced_items` — never guess a price.
- **Decode downloaded JSON explicitly as UTF-8.** ~430 card names are accented; a wrong-charset response header would mojibake them.
- **Use `func.lower(col).like(...)`, not `ilike`,** for name search — SQLite's `LIKE` is case-insensitive for ASCII only, so `ilike` misses accented names.
- No SQLite-specific SQL: everything goes through the SQLAlchemy ORM so a Postgres swap stays cheap.
- **Install torch and torchvision together from the cu128 index, and re-run that install after any package that depends on torch.** `pip install open-clip-torch` silently replaces the CUDA build with a CPU one, and repairing torch alone then breaks torchvision (`operator torchvision::nms does not exist`).
- **Never derive a cache filename from an image URL.** 661 catalog images have no file extension, and two real card ids (`ex10-!`, `ex10-?`) contain characters illegal in NTFS filenames. Key on `card_id` and percent-encode it.
- **Recognition must report uncertainty, never guess.** A confidently wrong identification is the worst outcome this pipeline can produce — prefer an `ambiguous` result with ranked candidates. **Only a reading that proves OCR found the collector-number field may override the visual winner** — either a full `N/M` form (the `/` is the proof) or a letter-prefixed promo code like `SM102` (the prefix is the proof). **Bare digits may only confirm the visual top-1, never promote** — that is the `hgss4-1` guard, where `1/102` misread as `102` would otherwise turn a correct answer into a confidently wrong one.
- **Detection proposals are selected by which crop recognises best, not by which strategy ran first.** Each strategy in `detectors.py` proposes a quad; the service embeds every proposal (2.2 ms each) and keeps the best match, running OCR once on the winner. A single "better" detector was measured *not* strictly better — `otsu_rect` alone recovered 33 real failures but regressed 6 working scans; the chain regresses none.
- **Never count "found a card-shaped quad" as "found the card".** Adaptive thresholding scored 56/56 in an early comparison purely by returning the whole image border, whose aspect ratio passes the shape gate on a portrait photo. Verify a detector by running recognition on its output, and keep the `MAX_AREA_FRACTION` guard that rejects whole-frame quads.
- **`approxPolyDP` demanding exactly 4 vertices is what broke detection originally.** Real photos have rounded corners and noise, so it lands on 5–7 vertices and discards a visible card; fitting a rotated rectangle to the largest blob is the more robust primitive.
- **Score any detection change with `backend/scripts/evaluate_detection.py`.** It replays the real scans in `data/scans/` and fails the run on a single regression — a confidently wrong card is worse than a missed detection.
- **Report precision and coverage separately, never a blended "accuracy".** Counting a declined `ambiguous` result as a wrong answer conflates refusing to guess with guessing wrong, which are opposites in a system built on calibrated uncertainty.
- **Rectification must reject non-card-shaped quads.** Without the aspect gate it latches onto the card's interior artwork window on pale backgrounds and returns it stretched to full size, which nothing downstream can detect.

## Notes for Claude

<!-- Anything Claude should always keep in mind: gotchas, do-nots, priorities. -->
- Ask before running destructive or irreversible commands.
- **Never delete anything under the shared data store** (`C:\ClaudeKnowledge\Pokemon Project\data\`) — it holds 20,391 downloaded card images, a 40 MB FAISS index, the SQLite database, and 109 irreplaceable real scan photos. It is outside the repo and gitignored, so nothing there can be recovered from git. The repo's own `data/scans/batch_fixtures/` is tracked and safe.
- **Keep `AI_CONTEXT.md` current.** It is the onboarding document for any AI working on this repo, and a stale one is worse than none because it gets trusted. Update it — including the "Last updated" date — after any change to architecture, measured results, the roadmap, or a newly discovered gotcha. Rule of thumb: if a fresh AI would make a worse decision without knowing it, it belongs there.
- Match the style of surrounding code.
