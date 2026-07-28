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
| 0 | Foundation — card catalog, pricing layer, collection store | Designed |
| 1 | Single-card scan — photo → identified, valued card | Designed |
| 2 | Portfolio tracker — cost basis, P/L, price charts | Planned |
| 3 | Grade Predictor — CV centering/corner scoring + grading EV | Planned |
| 4 | Bulk cataloger — detect every card in one photo | Planned |
| 5 | Deal sniper + sealed EV — listings vs. sold comps, rip-vs-flip | Planned |
| 6 | Set-completion optimizer — cheapest path to finish a set | Planned |
| 7 | Counterfeit detector — holo pattern, rosette, texture analysis | Planned |

## Phase 1 in one line

Hybrid recognition: on-device rectification → visual embedding match **and** targeted OCR in
parallel → fused calibrated confidence → auto-confirm or top-3 user pick. Two engines that fail on
different inputs, so the system knows when it is unsure.

## Next step

Write the Phase 0+1 implementation plan.
