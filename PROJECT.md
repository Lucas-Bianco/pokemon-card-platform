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
| 0 | Foundation — card catalog, pricing layer, collection store | **Complete** |
| 1 | Single-card scan — photo → identified, valued card | Designed, next |
| 2 | Portfolio tracker — cost basis, P/L, price charts | Planned |
| 3 | Grade Predictor — CV centering/corner scoring + grading EV | Planned |
| 4 | Bulk cataloger — detect every card in one photo | Planned |
| 5 | Deal sniper + sealed EV — listings vs. sold comps, rip-vs-flip | Planned |
| 6 | Set-completion optimizer — cheapest path to finish a set | Planned |
| 7 | Counterfeit detector — holo pattern, rosette, texture analysis | Planned |
| 8 | On-device inference — quantized model in-browser, no server | Planned |

## Key decisions

- **Local-first.** All inference runs on Lucas's own machine (RTX 5070 Ti / 16 GB VRAM). Only the
  catalog + price sync touches the network, so scanning works offline.
- **Data source verified 2026-07-28.** `pokemontcg.io` supplies free **per-variant** pricing
  (holofoil vs. reverse-holofoil priced separately — exactly what variant disambiguation needs),
  TCGplayer refreshed daily. But the **API is badly degraded (2/12 requests succeeded)**, so the
  catalog is bulk-loaded from the [`pokemon-tcg-data`](https://github.com/PokemonTCG/pokemon-tcg-data)
  JSON dump instead, and all providers sit behind an interface so a fallback can be swapped in.
- **Setup hazards:** system Python is 3.14 (too new for the ML wheels — use a 3.12 venv), and
  Blackwell GPUs need a CUDA 12.8+ PyTorch build or they silently fall back to CPU.

## Phase 0 — shipped

Built 2026-07-29 ([plan](docs/superpowers/plans/2026-07-28-phase-0-foundation.md)). **69 tests passing.**

- **Catalog:** 174 sets, **20,444 cards** loaded locally from the
  [`pokemon-tcg-data`](https://github.com/PokemonTCG/pokemon-tcg-data) JSON dump. Sync is idempotent
  and resumable (commits per set), so a dropped connection mid-run costs one set, not the whole load.
- **Prices:** per-variant snapshots from pokemontcg.io behind a swappable provider interface,
  retry-hardened with backoff. Terminal errors (404/401) are not retried; 5xx and 429 are. Snapshots
  are immutable and deduped, so price history accrues from day one.
- **Collection:** add/remove/list with deliberately conservative valuation — an unpriced item counts
  as zero and is reported separately rather than guessed at.
- **API:** FastAPI over catalog, prices, and collection. Every price carries its `source` and
  `source_updated_at`.
- **Stack note:** SQLite via SQLAlchemy ORM (no SQLite-specific SQL), so a Postgres swap stays cheap.

**Why staleness is surfaced rather than blended** — real data for `base1-4` on 2026-07-29:
cardmarket said **$1531.00** (updated 07/01), tcgplayer said **$800.43** (updated 07/29). Nearly 2×
apart. Collapsing those into a single "market price" would be actively misleading, so the API never
does.

## Carried into Phase 1 (from the final Phase 0 review)

Verified against the real 20,444-card database — resolve these when planning Phase 1:

**Data facts that affect the image pipeline**
- **0 cards have a missing `image_small`**, 0 duplicates, 0 orphan `set_id`s. The catalog is clean
  enough to build the embedding index on directly.
- **Images span two CDNs** — 19,783 on `images.pokemontcg.io`, 661 on `images.scrydex.com`. The
  post-acquisition migration is visibly in progress.
- **661 URLs have no file extension**, ending in `/small` rather than `.png`. Any cache-filename
  logic doing `url.rsplit(".", 1)[-1]` breaks on 3% of the catalog.

**Gaps to close before the scan loop works end to end**
- **Only 2 of 20,444 cards have any price snapshot.** Prices arrive solely via
  `cardplatform refresh-prices <ids>`. A scan of an arbitrary card returns "unpriced" until there is
  a bulk backfill job or an on-demand `POST /cards/{id}/prices/refresh`.
- **No HTTP endpoint returns the *resolved* price.** `GET /cards/{id}/prices` returns every
  `(source, variant)` pair; the "which one is *the* price" rule lives only in
  `PriceService.latest_price`. Add `GET /cards/{id}/price?variant=…` so the scan UI does not
  reimplement it client-side.
- **`variant` is unvalidated free text.** A recognizer emitting `"reverse_holo"` instead of
  `"reverseHolofoil"` silently creates a row that can never be priced correctly.
- **`latest_price` hardcodes `"tcgplayer"` / `"cardmarket"` / `"aggregate"`**, so a second provider
  would persist snapshots yet stay invisible to valuation. Worth fixing before Phase 5 adds a source.
- Nowhere to record match confidence or the source photo for a recognized card.
- `cli.py` has 0% test coverage (87% overall). It was exercised manually against real data, but it
  is the one module where a typo ships undetected.

## Phase 1 in one line

Hybrid recognition: on-device rectification → visual embedding match **and** targeted OCR in
parallel → fused calibrated confidence → auto-confirm or top-3 user pick. Two engines that fail on
different inputs, so the system knows when it is unsure.

## Next step

Write the Phase 0+1 implementation plan.
