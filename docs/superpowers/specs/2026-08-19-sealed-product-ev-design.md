# Phase 05c — Sealed-Product Deal Sniper (flip-edge) Design

> **Status:** design, 2026-08-19. Sibling to `2026-08-03-deal-sniper-design.md` (Phase 05).
> Out-of-scope statement carried from that spec, §11: *"Sealed-product EV — the other
> half of Phase 05; needs sealed-product price data we don't have a provider for.
> Roadmap keeps it planned."* This phase closes that leg — partially, and honestly.

## 1. Goal

Find underpriced **sealed** Pokémon product listings on eBay (booster boxes, ETBs,
collection boxes, packs): for a free-text product query, fetch active listings (the buy
side) + recently-sold comps (the market reference), and rank listings by **flip-edge**
(`sealed_market − listing.price`). Honest empty states throughout — no fabricated edges,
no `$0`, distinct "no key" vs "no listings" vs "no sold comps" states.

## 2. Scope — what ships, what's deferred

**Ships (flip-edge, no master data needed):**
- A sealed listing/sold-comp provider (eBay Finding API, query-keyed).
- A read-only `SealedDealEngine` computing flip-edge per listing.
- `GET /sealed/deals?q=&limit=` + `cardplatform find-sealed-deals` CLI.
- A 7th "Sealed" frontend tab + site roadmap update.

**Deferred (documented follow-ups, NOT this phase):**
- **Rip EV (opening for expected pull value)** — needs a product-contents master +
  pull-rate tables we do not have. This is the same "blocked on labelled/curated data"
  class as the full Grade predictor (§3b shipped a spread, not a prediction). We ship the
  flip-edge now and defer rip EV exactly as §3b deferred P(grade).
- **Sealed-product master / catalog** (`SealedProduct` table, set→product mapping,
  pack counts, contents JSON) — not needed for query-keyed flip-edge; deferred to the
  rip-EV phase that needs contents.
- **Persisting sealed deals / market snapshots** — deals are on-demand (mirrors sold-comps:
  no snapshot writes, no new table).
- **TCGplayer sealed product API / OAuth** — eBay Finding API is the one-key path today.

## 3. Why this is the honest shippable unit

The project's load-bearing value is **never confidently wrong / never fake missing data.**
A sealed flip-edge needs only a *market price* (sold comps) + an *asking price* (active
listing) — both already fetchable from eBay via the existing Finding API adapter. It needs
**no pull rates**, so it is not blocked on any data we lack. Rip EV *is* blocked (no pull
rates), so it is deferred — mirroring §3b (spread now, P(grade) later) and §05 (deal sniper
shipped with honest-empty when no key). Shipping flip-edge now is the verified/honest path;
rip EV is the data-blocked path.

## 4. Architecture

```
user query ("scarlet violet booster box")
   ↓
SealedListingsProvider.fetch_listings_by_query(query)   eBay findItemsByKeywords
SealedListingsProvider.fetch_sold_listings_by_query(query, limit)   eBay findCompletedItems
   ↓
SealedDealEngine.assess(query, limit)
   sealed_market = median(sold comp prices)   # None if no comps -> all flip_edges null
   per listing: flip_edge = sealed_market.price − listing.price   # None if either missing
                 is_flip = flip_edge >= sealed_flip_min_abs AND >= sealed_flip_min_pct * market
                 deal_score = flip_edge if flip_edge is not None else None   # nulls last
   sort desc by deal_score
   ↓
GET /sealed/deals  ->  SealedDealsResponse{query, deals[], sealed_market, flags, thresholds}
```

**Read-only, no writes, no new table, no schema change.** The engine composes a provider +
`settings`; it never resolves a price ad hoc (the only "price" is the median sold comp,
which IS the market reference, sourced via the provider — never fabricated). Reuses the
existing `CARDPLATFORM_LISTINGS_API_KEY` (eBay App ID) — sealed products **are** eBay
listings, so no new key.

## 5. File structure

**Backend (new package `sealed/`):**
- `sealed/__init__.py`
- `sealed/provider.py` — `SealedListing`, `SealedSoldComp` (frozen dataclasses, no
  `card_id`/`variant` — they carry `query`), `SealedListingsProvider` Protocol
  (`fetch_listings_by_query`, `fetch_sold_listings_by_query`).
- `sealed/engine.py` — `SealedPricePoint`, `SealedThresholds`, `SealedDealAssessment`,
  `SealedDealResult`, `SealedDealEngine` (read-only).
- `sealed/api_models.py` — `SealedPricePointOut`, `SealedThresholdsOut`,
  `SealedDealAssessmentOut`, `SealedDealsResponse` (Pydantic v2, `from_attributes`).

**Backend (additive edits):**
- `prices/ebay_listings.py` — add `fetch_listings_by_query` / `fetch_sold_listings_by_query`
  + `_parse_by_query` / `_parse_completed_by_query`; DRY-extract
  `_extract_listing_fields(item)` / `_extract_sold_fields(item)` shared with the existing
  `_parse` / `_parse_completed` (single-card path behavior unchanged).
- `config.py` — `sealed_flip_min_abs=20.0`, `sealed_flip_min_pct=0.05`,
  `sealed_sold_comp_limit=10` (validator clamp [1,100]).
- `api.py` — `GET /sealed/deals` + `EbayListingsProvider`/`SealedDealEngine` construction.
- `cli.py` — `find-sealed-deals --query --limit`.

**Frontend:**
- `api/types.ts` — `SealedDealAssessment`, `SealedPricePoint`, `SealedThresholds`,
  `SealedDealsResponse`.
- `api/client.ts` — `getSealedDeals(query, limit)`.
- `components/SealedDeals.tsx` — search + ranked feed + flip chips + honest empty states.
- `components/AppShell.tsx` — 7th "Sealed" `TabView` + `TabButton` + branch.

**Site + docs:**
- `site/app/sections/data.ts` — roadmap row 05 sealed → in-progress.
- `AI_CONTEXT.md` — §2 roadmap + new §15 writeup.
- `PROJECT.md` — roadmap + next-step.
- `docs/superpowers/plans/2026-08-19-sealed-product-ev.md` — this phase's task plan.

## 6. Sacred constraints (held)

- **No ad-hoc price resolution.** The only price the engine produces is
  `sealed_market` = median of sold comps fetched via the provider. Never fabricated.
- **No snapshot writes, no new table, no schema change.** On-demand, like sold-comps.
- **Honest empty states — no `$0`, no fabricated edge.** `flip_edge` is null when
  `sealed_market` is None (no sold comps) or `listing.price` is None; `is_flip` is False
  when `flip_edge` is None. Distinct flags: `listings_unavailable` (no key) vs
  `listings_empty` (key set, no listings) vs `comps_unavailable`/`comps_empty`.
- **Degrade to `[]`, never raise.** The provider never raises; no key → `[]` without a
  network call; 4xx terminal one attempt; 5xx/429/transport retry then `[]`; bad JSON → `[]`.
- **No `data/` deletion.** Recognition + 105-scan baseline untouched (no recognition code
  changes this phase).
- `func.lower().like` n/a (no DB text search this phase). `UtcDateTime` n/a (no new tables).

## 7. The flip-edge math (exact)

```
sold_comp_prices = [c.price for c in comps]      # comps already EndedWithSales-gated
sealed_market = median(sold_comp_prices) if sold_comp_prices else None

for listing in listings:
    flip_edge = (sealed_market - listing.price)        if sealed_market is not None
                                                  and listing.price is not None
               else None
    is_flip  = (flip_edge is not None
                and flip_edge >= sealed_flip_min_abs
                and flip_edge >= sealed_flip_min_pct * sealed_market)
    deal_score = flip_edge if flip_edge is not None else None   # nulls last

sort by deal_score desc, nulls last
```

`sealed_market` is a **median** (not mean) — robust to one outlier comp. It is an
**indicative lead** ("investigate before buying"), not a guaranteed arbitrage — the same
framing as the Phase 05 deal sniper. Selling fees are intentionally NOT subtracted (gross
edge), matching `DealEngine`'s treatment; the UI says so.

## 8. Open questions (auto-mode defaults)

- **Market reference = median of recent sold comps** (not lowest active listing, not mean).
  Median is robust; sold comps are real transactions (EndedWithSales-gated).
- **Reuse `CARDPLATFORM_LISTINGS_API_KEY`** — sealed products are eBay listings; no new key.
  A separate `sealed_*` key is a documented follow-up if a non-eBay sealed source is added.
- **No product master.** Query-keyed; the "product" is the user's free-text query. A
  `SealedProduct` master is deferred to the rip-EV phase.
- **`limit` (listings assessed)** — API and CLI differ by design. The API endpoint
  `GET /sealed/deals` uses `Query(20, ge=1, le=50)`, which **rejects** out-of-range
  values with a 422 (in-range default 20). The CLI `find-sealed-deals` **clamps**
  (`max(1, min(limit, 50))`) for friendliness, so an out-of-range `--limit` still runs
  against the nearest in-bounds value rather than erroring. `sealed_sold_comp_limit`
  [1,100] default 10.
- **7th bottom-nav tab "Sealed"** (the shell already extends to 6; a 7th is the established
  pattern, and sealed is a distinct surface, not card-scoped — a tab beats a CardDetail
  sub-panel).