# CLAUDE.md

This file gives Claude Code guidance when working in this repository.

## Project overview

<!-- One or two sentences: what this project is and what it does. -->
ClaudeKnowledge — a local-first Pokemon trading card recognition and valuation platform. Phase 0 is the data foundation: catalog, pricing, collection store.

## Setup

<!-- How to get the project running from a fresh clone. -->
```sh
# install dependencies
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\backend[dev]"
```

## Commands

<!-- The commands you run most often. Keep these accurate — Claude will trust them. -->
- Build: no build step configured yet.
- Test: `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest` (run from repo root)
- Lint / format: no lint/format step configured yet.
- Run / dev server: `C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --reload --port 8000`
- Coverage: `C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest --cov=cardplatform --cov-report=term-missing`
- Sync the card catalog: `C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe sync-catalog` (idempotent, resumable)
- Fetch prices: `C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe refresh-prices base1-4 hgss4-1`

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

## Notes for Claude

<!-- Anything Claude should always keep in mind: gotchas, do-nots, priorities. -->
- Ask before running destructive or irreversible commands.
- Match the style of surrounding code.
