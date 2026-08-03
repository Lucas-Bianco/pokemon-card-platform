# Deal Sniper / Rip-vs-Flip — Design Spec

**Owner:** Lucas
**Date:** 2026-08-03
**Phase:** 05 — Deal sniper & sealed EV (this ships the *deal sniper / rip-vs-flip* leg; sealed EV
remains planned)
**Status:** Approved for planning (auto mode)
**Predecessors:** Phase 3b (graded-price provider + grading-upside spread), Phase 3c (listings
provider + `ListingsService` + watchlist/alerts shell)

---

## 1. The one sentence

**Point the app at an active marketplace listing and it tells you whether that listing is a good
deal — to *rip* (buy below real market value) or to *flip* (buy raw, grade, sell at the PSA-10 comp)
— with honest nulls whenever the data to compute an edge is missing.**

This is the project's reason for existing. From `PROJECT.md`: *"Collectibles are an inefficient
market where a real edge exists — mispriced listings, grading arbitrage, EV on sealed product."*
Phase 3b shipped the graded-price leg (the *flip* inputs); Phase 3c shipped the active-listings leg
(the candidate deals). This phase joins them into an evaluation: **is this listing a deal?**

## 2. The deal model

For one active listing of a card, four inputs come from existing, never-ad-hoc services:

| Input | Source | Honest when missing |
|---|---|---|
| `listing.price` | `ListingsService.latest_listings(card_id, variant)` (3c) | no listings → no deals |
| `raw_market` | `PriceService.latest_price(card_id, variant)` (Phase 0) | `null` → no rip edge |
| `psa9_comp`, `psa10_comp` | `GradedPriceService.latest_graded(card_id, variant, grade, "PSA")` (3b) | `null` → no flip edge |
| `grading_fee` | `settings.grading_fee` (3b, default PSA bulk ~$25) | always present |

From these, two edges:

```
rip_edge        = raw_market.price − listing.price                      # null if no raw_market
flip_edge_to_9  = psa9_comp.market  − listing.price − grading_fee       # null if no psa9_comp
flip_edge_to_10 = psa10_comp.market − listing.price − grading_fee       # null if no psa10_comp
```

A **rip** is a listing priced below the raw sold-comp market — buy to hold/collect at a discount.
A **flip** is a listing whose raw price plus grading fee leaves meaningful headroom under the
graded comp — buy raw, mail it in, sell the slab. Both edges are *indicative leads*, not guaranteed
arbitrage: eBay keyword listings carry seller-mislabel noise, and a grade is a gamble. The UI says
"investigate before buying" — the same "never confidently wrong" value the recognition pipeline holds.

**Thresholds (settings, calibrated to filter noise not to manufacture deals):**

- A listing is flagged `is_rip` iff `rip_edge >= deal_rip_min_abs` AND
  `rip_edge >= deal_rip_min_pct * raw_market.price` (default `$2` and `0.10` — at least $2 and at
  least 10% below market).
- A listing is flagged `is_flip` iff `flip_edge_to_10 >= deal_flip_min_abs` (default `$20` —
  grading fee plus meaningful profit). `flip_edge_to_9` is shown alongside as the conservative case.
- `deal_score` (for ranking) = `max(rip_edge or 0, flip_edge_to_10 or 0)`; nulls sort last.

No edge is ever fabricated. A missing input nulls the edge it feeds — never `$0`, never a fake
profit. Every price surfaces its `source` + `source_updated_at` (the staleness discipline).

## 3. What is new vs. what is reused

**Reused, untouched (sacred):** `PriceService.latest_price`, `GradedPriceService.latest_graded`,
`ListingsService.latest_listings` / `lowest_price`, the immutable `PriceSnapshot` /
`GradedPriceSnapshot` / `ListingSnapshot` tables, the watchlist/alerts engine from 3c, recognition,
the scan store, all 105 real scans.

**New backend code (additive):**

- `prices/ebay_listings.py` — the `EbayListingsProvider` (3c, currently a keyword-search stub that
  degrades to `[]`) is made **real**: it calls the eBay **Finding API** (`findItemsByKeywords`)
  with `SECURITY-APPNAME = CARDPLATFORM_LISTINGS_API_KEY`, builds the keyword from the catalog card
  (name + set + number), parses items to `ListingQuote`, keeps the never-raise / tenacity / degrade-to-`[]`
  pattern. **This also unblocks the 3c restock/new_listing/auction alerts** (which need real listings).
- `deals/engine.py` — `DealEngine.assess(card_id, variant)` → list of `DealAssessment` (one per
  active listing), read-only (computes from existing snapshots; writes nothing).
- `deals/api_models.py` — Pydantic v2 wire models (`DealAssessmentOut`, `DealCardOut`).
- `api.py` — `GET /cards/{card_id}/deals?variant=` (ranked deals for one card) and
  `GET /deals?card_ids=&limit=` (a cross-card feed: top deals across a set of cards — watched cards
  by default). Honest `listings_unavailable` / `listings_empty` flags.
- `cli.py` — `cardplatform find-deals <card_id> [--variant=]` (one-shot, prints ranked deals).
- `config.py` — `deal_rip_min_abs=2.0`, `deal_rip_min_pct=0.10`, `deal_flip_min_abs=20.0`.

**New frontend code:**

- A **Deals** bottom-nav tab (the shell becomes Scan · Vault · Alerts · **Deals** · Browse · More —
  six compact tabs, ~58px each, the deal feed's home). `components/Deals.tsx`: search a card or pull
  the user's watched cards → ranked deal cards, each showing the listing (price, source, condition,
  auction timer), the rip edge, the flip-to-10 / flip-to-9 edges, deal flags (rip/flip chips), source
  + staleness, and a "investigate before buying" caveat. Honest empty states throughout.
- `components/CardDetail.tsx` — each active listing row gains a **deal-score chip** (rip/flip edge +
  color), reusing the listings section already shipped in 3c.
- `api/client.ts` + `types.ts` — `getDeals(cardId, variant)`, `getDealsFeed(cardIds)`, `DealAssessment`
  type.

**New site code:**

- `site/app/sections/Deals.tsx` — a scroll-animated section: a rip-vs-flip diagram (two paths from a
  raw listing — "rip: sell into the raw market" vs "flip: grade → sell the slab") with the honest
  "indicative leads, not guaranteed arbitrage" caption. GSAP scrub + Framer reveal,
  `prefers-reduced-motion` static fallback, CSS defaults visible JS-off (matches Grading/Alerts).
- `site/app/sections/data.ts` — Phase 05 row → `status: "progress"`, subtitle "Deal sniper
  (rip-vs-flip) shipped — sealed EV still planned". `SHIPPED_COUNT` recomputed from `done` rows.

## 4. The honest-empty-states contract (the feature, not a workaround)

This phase extends the project's "never fake missing data" value to deals:

- **No listings source key** (`settings.listings_api_key is None`) → `listings_unavailable: true`,
  feed shows "Set a listings source key (eBay) to find deals." Never an empty list dressed as "no
  deals right now."
- **Key set, zero listings returned** → `listings_empty: true`, feed shows "No active listings for
  this card right now."
- **Listings present, no raw market** → every listing shows `rip_edge: null` + "no market price",
  flip edges still computed if graded comps exist.
- **No graded comps** → `flip_edge_*: null` + "graded prices unavailable — set a graded-price
  provider key"; rip edge still computed.
- **Neither raw nor graded** → listing shows with `—` edges, "no market price". Still listed (it
  is a real listing) but not scored.
- **Edges below thresholds** → listing listed, no deal chip, "not a deal at this price". Never
  inflated to a deal.
- Every price carries `source` + `source_updated_at`; stale prices show a staleness marker.

## 5. Sacred constraints (held)

- **No ad-hoc price resolution.** Edges use only `PriceService.latest_price`,
  `GradedPriceService.latest_graded`, `ListingsService.latest_listings`. No direct snapshot queries
  in the engine or API.
- **Snapshots immutable.** `DealEngine` is read-only; it writes nothing. (It does not persist deal
  scores — they're computed on demand from the latest snapshots, so they never go stale in storage.)
- **Surface staleness.** Every price in a `DealAssessment` carries `source` + `source_updated_at`.
- **Providers degrade to `[]`, never raise.** The eBay adapter keeps the 3c contract; the engine
  treats `[]` listings as "no listings", not an error.
- **`func.lower(col).like`** for any text search (CLI / API card-name search).
- **`UtcDateTime`** for any new tz-aware column (none expected — read-only phase).
- **Python 3.12 via `backend/.venv`**; **never delete anything under `data/`**; only edit within
  `C:\ClaudeKnowledge`; commit all new code to GitHub.

## 6. The eBay Finding API adapter (the realness leg)

`EbayListingsProvider.fetch_listings(card_id, variant)`:

1. Resolve the catalog card (name, set name, number) from `card_id` via the catalog store.
2. Build keyword: `"<name> <number>"` (set name omitted if it adds noise — eBay keyword search
   over-matches on set names; tuned in tests). Percent-encode.
3. GET `https://svcs.ebay.com/services/search/FindingService/v1` with
   `OPERATION-NAME=findItemsByKeywords`, `SECURITY-APPNAME=<key>`,
   `RESPONSE-DATA-FORMAT=JSON`, `REST-PAYLOAD`, `keywords=<kw>`,
   `paginationInput.entriesPerPage=20`. No `itemFilter` by grade (we want raw listings, graded
   listings will have a high flip-to-10 edge that the thresholds naturally filter).
4. Parse `findItemsByKeywordsResponse.searchResult.item[]` → `ListingQuote`:
   - `listing_id = item.itemId`
   - `title = item.title`
   - `price = float(item.sellingStatus.currentPrice.value)`, `currency = ....__value__` (the
     `currencyId` attr)
   - `listing_type` from `item.listingInfo.listingType` (`FixedPrice` → `"fixed"`,
     `Auction`/`AuctionWithBIN` → `"auction"`)
   - `auction_end_at = item.listingInfo.endTime` (ISO, tz-aware) for auctions, else None
   - `url = item.viewItemURL`
   - `condition = item.condition.conditionDisplayName` if present
   - `source = "ebay"`, `source_updated_at = None` (Finding API gives no per-item updated-at)
5. **Never raises.** No key → `[]`. 404/401/transport/parse → tenacity retry on 5xx/429, terminal
   one-attempt on 404/401/bad-JSON, `RetryError`/parse failure → `[]`. Exactly the
   `PkmnPricesProvider` shape.

**Caveats documented in the module docstring:** eBay keyword search returns seller-mislabel noise
(a card titled "Charizard" may be a different Charizard); the deal engine treats edges as leads;
the user verifies the listing before buying. The `ListingsService` already dedupes immutable
snapshots on `(card_id, variant, source, listing_id, source_updated_at)`, so re-fetches don't
double-count.

**Key acquisition (documented in the module + AI_CONTEXT follow-up):** a free eBay developer
account at `developer.ebay.com` → My Apps → create an app → the `App ID (Client ID)` is the
`SECURITY-APPNAME`. Set as `CARDPLATFORM_LISTINGS_API_KEY`. Until set, the adapter degrades to `[]`
and the whole deal surface is honestly empty — the phase ships regardless.

## 7. API surface

```
GET /cards/{card_id}/deals?variant=
  → 200 {card_id, variant,
         listings_unavailable: bool,   # no listings source key
         listings_empty: bool,         # key set, 0 listings
         deals: [DealAssessmentOut],    # ranked by deal_score desc, nulls last
         thresholds: {deal_rip_min_abs, deal_rip_min_pct, deal_flip_min_abs}}

DealAssessmentOut = {
  listing_id, title, price, currency, url, condition, listing_type,
  auction_end_at | null, fetched_at,
  raw_market: {price, source, source_updated_at} | null,
  rip_edge: float | null,
  psa9_comp: {market, source, source_updated_at} | null,
  psa10_comp: {market, source, source_updated_at} | null,
  flip_edge_to_9: float | null,
  flip_edge_to_10: float | null,
  grading_fee: float,
  deal_score: float | null,
  is_rip: bool, is_flip: bool
}

GET /deals?card_ids=<csv>&limit=20
  → 200 {listings_unavailable: bool, deals: [DealAssessmentOut], ...}
  # card_ids defaults to the user's active watchlist card_ids (watches with a card_id).
  # Cross-card: assesses each card, merges, ranks by deal_score, truncates to limit.
  # Honest-empty per-card merges into the overall honest-empty flags.
```

404 on unknown `card_id` (matches the 3c watchlist endpoint). No 422 beyond FastAPI defaults
(`variant` is free text, validated only where the existing services require it — they tolerate
None).

## 8. CLI

```
cardplatform find-deals <card_id> [--variant=holofoil]
  # builds the engine, prints ranked deals: price, rip_edge, flip_to_10, flags, url
  # "no listings source key" / "no active listings" / "no market price" honest messages
```

No poll loop (deals are on-demand, not time-sensitive like alerts). A future "deal alert" (fire
when a new listing is a deal) is out of scope here — it would compose the 3c alert engine with
this evaluator, and is a documented follow-up.

## 9. Frontend

**Deals tab (`components/Deals.tsx`):**
- Top: a search box (debounced 300ms → `GET /cards?name=`) and a toggle "Show deals for my
  watched cards" (default on if the watchlist is non-empty).
- A ranked list of deal cards. Each card:
  - Header: card name + number + variant, listing price (money, no thousands comma —
    `formatMoney`'s `toFixed(2)`), source badge ("eBay"), condition, auction timer (relative) if
    auction.
  - Edge block: **Rip** row (raw market, rip edge, "below market" / `—`), **Flip** row (PSA-10
    comp, flip-to-10, flip-to-9, "after $<fee> grading fee" / `—`).
  - Deal chips: 🟢 RIP / 🟡 FLIP / none, per thresholds.
  - Staleness: small "updated <relative>" under each price.
  - Footer: "Investigate before buying — keyword listings carry seller-mislabel noise."
  - Tap → opens the listing URL (external) and/or deep-links to CardDetail.
- Honest empty states per §4.

**CardDetail deal scores:** each listing row in the existing listings section gets a compact
deal-score chip (rip / flip edge + color). Reuses the 3c listings rendering; adds the chip from a
`getDeals` fetch alongside the listings fetch.

**`api/client.ts` + `types.ts`:** `getDeals(cardId, variant)`, `getDealsFeed(cardIds, limit)`,
`DealAssessment`, `DealFeed` types. `expectJsonOrDetail` for 422 surfacing (matches 3c).

**Tests (vitest, text + selectors, no layout):** Deals renders ranked deals; honest-empty for
`listings_unavailable` / `listings_empty` / no-raw-market / no-graded-comps; deal chips appear iff
thresholds met; "investigate" caveat present; watchlist toggle drives the feed. CardDetail chip
renders. Existing 90 tests stay green.

## 10. Site

`site/app/sections/Deals.tsx` — scroll-scrubbed rip-vs-flip diagram: a raw listing node splits
into two paths — **Rip** (→ raw sold-comp market, "buy below market") and **Flip** (→ grading
→ PSA-10 slab comp, "buy raw, grade, sell"). Bars fill as you scroll. Honest caption: *"Deal
edges are indicative leads from marketplace keyword search, not guaranteed arbitrage — always
verify the listing."* `prefers-reduced-motion` static; CSS visible JS-off. Wire into `page.tsx`
after Alerts. Roadmap row 05 → in-progress subtitle updated. Rebuild → `docs/` (preserve
`.nojekyll` + `docs/superpowers/`).

## 11. Out of scope (deliberately deferred)

- **Sealed-product EV** — the other half of Phase 05; needs sealed-product price data we don't
  have a provider for. Roadmap keeps it planned.
- **Deal alerts** — firing a 3c alert when a new listing is a deal. Composes the alert engine
  with this evaluator; a clean follow-up, not needed for the deals surface.
- **Persisting deal scores** — computed on demand; no `deal_snapshots` table. If we later want
  deal history / "deal expired", a snapshot table is the follow-up.
- **Multi-source listings** — only eBay in this phase; the provider Protocol keeps a second
  source swappable (TCGplayer marketplace, etc.).
- **A "best deals across the whole 20k catalog" scan** — `GET /deals` scopes to watched + searched
  cards; a full-catalog scan is a bulk job, deferred.
- **Grade-aware listing filtering** — we do NOT filter listings by grade (we want raw); graded
  listings that slip through are filtered by their low flip edge naturally.

## 12. Auto-mode design decisions (made, not asked)

- **6th bottom-nav tab** (Deals) over folding into Browse — the deal feed is the phase's home and
  a 6th compact tab fits a 360px phone; matches the CollectorVault/CCN pattern the user chose.
- **eBay Finding API** over Browse API — one `SECURITY-APPNAME` key (no OAuth token refresh),
  simpler to obtain and implement; Browse API is a documented upgrade path.
- **Read-only engine** (no deal snapshots) — deals are computed on demand from the latest
  snapshots, so they never go stale in storage and the engine stays read-only (sacred-snapshot-safe).
- **Thresholds as settings** with noise-floor defaults ($2 / 10% / $20) — filter noise without
  manufacturing deals.
- **Keyword = name + number** (set name omitted) — set names over-match on eBay; tuned in tests.

## 13. Verification (end-to-end)

- **Backend:** `backend/.venv/Scripts/python -m pytest` (443 → N, all green). New tests: eBay
  adapter (mock httpx: degrades to `[]` w/o key, parses items, auction/fixed mapping, never
  raises), DealEngine (edge math, honest nulls when raw/graded missing, threshold flags, ranking
  nulls-last), deals API (honest flags, 404 unknown card), CLI `find-deals`. Manual:
  `cardplatform find-deals base1-4` with a key → ranked deals; without → "no listings source key".
  `GET /cards/base1-4/deals?variant=holofoil` returns ranked deals with honest flags.
- **Frontend:** vitest green (90 → N); `npm run build` clean. Manual smoke (backend :8000,
  frontend :5173): open Deals tab → search a card → see ranked deals / honest empty states; a deal
  chip on CardDetail listing rows.
- **Site:** `npm --prefix site run build` → `out/` → `docs/`; `docs/index.html` shows the Deals
  section with scroll-scrub; `docs/superpowers/` intact; push → live Pages redeploy.
- **Sacred constraints:** only `latest_price` / `latest_graded` / `latest_listings`; read-only
  engine (no snapshot writes); staleness surfaced; honest empty states; no `data/` deletions.