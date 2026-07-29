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
- Run / dev server: `C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --reload --port 8000` (only works once Task 12 creates the `cardplatform.api` module)

## Project structure

<!-- Key directories and what lives in them. -->
- `.claude/` — Claude Code configuration (settings, commands, agents, skills).
- `backend/` — the `cardplatform` Python package (source in `backend/src/cardplatform/`, tests in `backend/tests/`).

## Conventions

<!-- Coding style, naming, patterns to follow or avoid. -->
- 

## Notes for Claude

<!-- Anything Claude should always keep in mind: gotchas, do-nots, priorities. -->
- Ask before running destructive or irreversible commands.
- Match the style of surrounding code.
