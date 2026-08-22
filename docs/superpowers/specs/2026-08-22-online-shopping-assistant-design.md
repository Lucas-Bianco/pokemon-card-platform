# Online Shopping Assistant — Design (Phase E, roadmap row 13)

> Status: designed 2026-08-22. Read-only feature. Reuses the eBay Finding API
> provider, the Phase 07 authenticity module, the sealed catalog, the card
> catalog + price layer. No new API key, no DB writes, no new tables, no
> `data/` writes.

## Goal

Paste an eBay *listing URL* (an active listing) → the app fetches that single
listing's facts and runs a **deal / worth / authenticity** read against it. The
honest form of "is this listing worth buying?" — it proves the comparison
(sold-comps median or catalog market price + source + staleness) and never
fabricates a verdict when the data isn't there.

This is the unifying surface: it composes the three existing pillars —
- **deal-sniper / flip-edge** (`sealed/engine.py`, `deals/engine.py`) → the deal read,
- **price + sold-comps** (`PriceService`, `EbayListingsProvider.fetch_sold_listings_by_query`) → the worth read,
- **authenticity** (`authenticity/consistency.py`, `authenticity/checklist.py`) → the authenticity read (card matches only).

## Non-goals (honest scope)

- **eBay only.** No TCGplayer/PriceCharting/cardmarket URL support (the existing
  provider is eBay-only; multi-source is a documented follow-up).
- **Active listings only.** A pasted sold-listing URL is out of scope; the
  assistant fetches the live listing via `getSingleItem`.
- **No listing-image OCR.** The authenticity check uses the *title*-extracted
  printed number (the `NN/NNN` collector-number convention), not image OCR. If
  the title has no such token, the consistency result is honestly `unread`.
- **No verdict on fakes.** Mirrors Phase 07: a mismatch is "wrong title→card
  match OR counterfeit, indistinguishable", never a fake/real verdict.
- **No persistence.** The assessment is computed on demand and discarded; no
  new table, no scan_log write.

## Architecture

```
GET /shop/assess?url=<ebay_url>&limit=<n>
  │
  ├─ parse_ebay_item_id(url)  → item_id | None   (422 if None)
  ├─ EbayListingsProvider.fetch_listing_by_id(item_id) → SealedListing | None
  │     (no key → None [listing_unavailable]; bad id → None [listing_not_found])
  ├─ ShopAssessor._match(title) → MatchResult      (sealed → card → none)
  ├─ ShopAssessor._deal(listing, match) → DealResult
  │     sealed → median(sold comps by product.name) ; card → PriceService.latest_price
  └─ ShopAssessor._authenticity(match) → AuthenticityResult | None   (card only)
  → ShopAssessmentOut
```

One new backend module `cardplatform/shop/` (assessor + wire models), one
addition to `prices/ebay_listings.py` (the single-item fetch + URL parser), one
new route in `api.py`, one new frontend tab `ShopAssistant.tsx`, and the 13th
"Shop" nav tab.

## Fixed contracts (the fan-out agents build against these exactly)

### 1. `prices/ebay_listings.py` — additions (Agent A)

**Module-level function:**
```python
def parse_ebay_item_id(url: str) -> str | None:
    """Extract the eBay item ID from a listing URL.

    Accepts any ebay.* domain and the /itm/<digits> path segment (with optional
    query suffix). Returns the digit string, or None if the URL is not an eBay
    listing URL. Pure, no network, no settings.
    """
```
Regex: `r"ebay\.[a-z.]+/itm/(\d+)"` (case-insensitive). First match group, or None.

**Provider method:**
```python
class EbayListingsProvider:
    def fetch_listing_by_id(self, item_id: str) -> SealedListing | None:
        """Fetch a single active listing by eBay item ID via Finding API getSingleItem.

        No key → return None without a network call. Transport/4xx/5xx/parse
        errors → None (degrade, never raise). Returns a SealedListing with
        source="ebay", or None if the item is not found / unparseable.
        """
```
- Calls `OPERATION-NAME=getSingleItem`, `itemId=<item_id>`, same
  `SECURITY-APPNAME` + `listings_base_url` + tenacity retry as `_search`.
- Unwraps `getSingleItemResponse[0].item[0]` via the existing `_first` helper
  (handle both list- and dict-wrapped responses defensively).
- Reuses `_extract_listing_fields` for the core fields, **then** pulls
  `sellerInfo.sellerUserName` (→ seller) and `pictureURL[0]` / `galleryURL`
  (→ image_url) from the raw item dict separately — **do not modify
  `_extract_listing_fields`** (it is shared by 4 existing parse paths; the
  existing `SealedListing`/`ListingQuote`/`SoldComp` construction must not
  change). `fetch_listing_by_id` builds its own `SealedListing` and stashes
  seller + image_url on it via two **new optional fields** added to
  `SealedListing` (`seller: str | None = None`, `image_url: str | None = None`)
  — these default to None so all existing construction sites are unaffected.
- `source_updated_at=None` (a live fetch has no snapshot timestamp).

**Tests** (`tests/test_ebay_listing_by_id.py`): `parse_ebay_item_id` (happy
`/itm/123` → "123"; with query suffix; non-ebay URL → None; no `/itm/` → None;
empty → None) + `fetch_listing_by_id` (no key → None no network [monkeypatch
httpx.get to assert not called]; happy → SealedListing with seller+image; bad
id/404 → None; parse error → None). Stub `httpx.get` to return canned
`getSingleItemResponse` JSON.

### 2. `cardplatform/shop/assess.py` + `shop/__init__.py` + `shop/api_models.py` (Agent B — owns the whole shop backend module)

**`shop/assess.py`:**
```python
@dataclass(frozen=True)
class ShopListing:
    item_id: str
    title: str | None
    price: float | None
    currency: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    seller: str | None
    image_url: str | None
    url: str | None
    source: str = "ebay"

@dataclass(frozen=True)
class ShopMatch:
    kind: Literal["card", "sealed", "none"]
    confidence: Literal["high", "low"]  # "low" always for card; "high" for sealed; "none"→"low"
    card_id: str | None = None
    card_name: str | None = None
    card_number: str | None = None
    card_rarity: str | None = None
    set_name: str | None = None
    sealed_slug: str | None = None
    sealed_name: str | None = None

@dataclass(frozen=True)
class ShopDeal:
    market: float | None
    market_source: str | None
    market_source_updated_at: str | None
    sold_comps_count: int          # 0 for cards (not applicable)
    edge: float | None             # market - listing.price ; None if either missing
    is_deal: bool                  # edge >= min_abs and edge >= min_pct * market
    min_abs: float
    min_pct: float
    market_unavailable: bool       # no key (sealed comps path)
    market_empty: bool             # key set, 0 comps (sealed) ; for card: market is None

@dataclass(frozen=True)
class ShopAuthenticity:
    caveat: str
    consistency: ConsistencyResult   # from authenticity.consistency (already a frozen dataclass)
    checklist: list[ChecklistItem]   # from authenticity.checklist (already frozen dataclasses)

@dataclass(frozen=True)
class ShopAssessment:
    url: str
    item_id: str | None
    listing_unavailable: bool      # no key
    listing_not_found: bool         # key set, fetch returned None
    listing: ShopListing | None
    match: ShopMatch
    deal: ShopDeal | None          # None when match.kind == "none"
    authenticity: ShopAuthenticity | None   # card matches only; else None
    caveat: str

class ShopAssessor:
    def __init__(self, session: Session, settings: Settings, provider: SealedListingsProvider) -> None: ...
    def assess(self, url: str, limit: int = 6) -> ShopAssessment: ...
```

**`assess` flow:**
1. `item_id = parse_ebay_item_id(url)`. (The route 422s on None before calling;
   assessor still guards: if `item_id is None` → `listing_unavailable` per key,
   `listing=None`, `match.kind="none"`, `deal=None`, `authenticity=None`.)
2. `key_set = bool(settings.listings_api_key)`.
3. `listing_data = provider.fetch_listing_by_id(item_id)` if `item_id` and
   `key_set` else None. Map to `ShopListing` (or None).
4. `listing_unavailable = not key_set`; `listing_not_found = key_set and
   listing_data is None`.
5. `_match(title)`:
   - **Sealed**: `SealedCatalogService(self.session).search(query=title)` →
     candidates whose `name.lower()` is a substring of `title.lower()`. Pick the
     longest-`name` candidate (most specific). If found → `kind="sealed"`,
     `confidence="high"`, `sealed_slug`/`sealed_name` set.
   - **Card** (only if no sealed match): query `Card` by
     `func.lower(Card.name).like(f"%{token}%")` for the longest title token
     that yields a match; among candidates whose `name.lower()` is a substring of
     the title, pick the longest-`name`. If found → `kind="card"`,
     `confidence="low"`, `card_id`/`card_name`/`card_number`/`card_rarity`/
     `set_name` (via `card.card_set.name`) set.
   - Else `kind="none"`, `confidence="low"`.
6. `_deal(listing, match, limit)`:
   - `match.kind == "none"` → `deal=None`.
   - **Sealed**: `comps = provider.fetch_sold_listings_by_query(sealed_name,
     limit)` (degrades to []); `market = median([c.price for c in comps if c.price
     is not None])`; `market_source="ebay"`, `market_source_updated_at=None`,
     `sold_comps_count=len(comps)`; `market_unavailable = not key_set`;
     `market_empty = key_set and not comps`; thresholds =
     `settings.sealed_flip_min_abs` / `sealed_flip_min_pct`.
   - **Card**: `snap = PriceService(self.session).latest_price(card_id,
     "normal")`; `market = snap.market if snap else None`;
     `market_source = snap.source if snap else None`;
     `market_source_updated_at = snap.source_updated_at if snap else None`
     (coerce `""` sentinel → None); `sold_comps_count=0`;
     `market_unavailable=False`; `market_empty = (market is None)`;
     thresholds = `settings.deal_rip_min_abs` / `deal_rip_min_pct`.
   - `edge = (market - listing.price) if (market is not None and listing and
     listing.price is not None) else None`.
   - `is_deal = edge is not None and edge >= min_abs and edge >= min_pct *
     market` (guard market>0).
   - If `listing is None` → `deal=None` (no listing price to compare).
7. `_authenticity(match)`:
   - `match.kind == "card"` only. Extract printed number from the listing title
     via `re.search(r"\b(\d{1,3})\s*/\s*\d{1,3}\b", title)` → first group, or
     None. Call `check_consistency(ocr_number=printed, card_number=card_number,
     card_id=card_id, card_name=card_name)`. `items = checklist_for(rarity=
     card_rarity, variant=None)`. Build `AuthenticityOut` (reuse the existing
     Pydantic shape) with a **listing-context caveat** (see below).
   - Else `None`.
8. `caveat`: a standing honesty banner — "An assessment, not a verdict. Market
   figures are proven eBay sold-comps or the catalog price with source + age;
   authenticity is a guide with 0 confirmed-counterfeit samples. A mismatch
   means a wrong title→catalog match OR a counterfeit — the app cannot tell
   which."

**Listing-context caveat** (replaces the scan-flow caveat wording): "A guide
for what to check on the listing's photos, not a verdict. The printed-number
check is read from the listing title, so a mismatch may mean the title→card
match is wrong, not that the listing is fake."

**`shop/api_models.py`:** Pydantic v2 wire models with
`model_config = ConfigDict(from_attributes=True)` on each, mirroring the
dataclasses field-for-field:
- `ShopListingOut`, `ShopMatchOut`, `ShopDealOut`, `ShopAssessmentOut`.
- `authenticity: AuthenticityOut | None` — **mirror** the three authenticity
  models locally in `shop/api_models.py` (do NOT import from `cardplatform.api` —
  `api.py` imports `shop.api_models`, so importing back would be circular).
  Declare `ConsistencyOut` (`printed_number`, `catalog_number`, `card_id`,
  `card_name` — all `str | None`; `match: str`; `note: str`), `ChecklistItemOut`
  (`id`, `title`, `what_to_check`, `caveat` — `str`; `applies: bool`), and
  `AuthenticityOut` (`caveat: str`, `consistency: ConsistencyOut`,
  `checklist: list[ChecklistItemOut]`), all with `from_attributes=True` so they
  map from `ConsistencyResult` / `ChecklistItem` / `ShopAuthenticity` directly.

**Tests** (`tests/test_shop_assessor.py`): in-process SQLite + `ensure_seed`
sealed catalog + a few seeded Cards + a stub `SealedListingsProvider` (a small
frozen-dataclass stub implementing `fetch_listing_by_id` +
`fetch_sold_listings_by_query`). Cases:
- sealed match (title contains "Elite Trainer Box") → deal with median, is_deal
  when under market, market_unavailable when no key, market_empty when 0 comps.
- card match (title contains a seeded card name) → deal uses latest_price,
  market_empty when no price snapshot, sold_comps_count 0.
- no match (gibberish title) → deal None, authenticity None, listing facts
  still present.
- authenticity: card match + title with `NN/NNN` → consistency `match`; title
  without → `unread`; checklist rarity-gate (holo vs non-holo).
- listing_unavailable (no key) + listing_not_found (key set, provider returns
  None).
- item_id None (defensive; route 422s first but assessor must not crash).

### 3. `api.py` — route (I own this, after the Workflow)

```python
@app.get("/shop/assess", response_model=ShopAssessmentOut)
def shop_assess(
    url: str = Query(..., min_length=8, description="An eBay listing URL, e.g. https://www.ebay.com/itm/123"),
    limit: int = Query(6, ge=1, le=10),
    session: Session = Depends(get_session),
) -> ShopAssessmentOut:
```
- `url = url.strip()`; if `parse_ebay_item_id(url) is None` → `raise
  HTTPException(422, detail="url must be an eBay listing URL (…/itm/<id>)")`.
- `provider = EbayListingsProvider(settings)`; `assessor = ShopAssessor(session,
  settings, provider)`; `result = assessor.assess(url, limit=limit)`.
- Return `ShopAssessmentOut.model_validate(result)`.
- Register the route near the other `/sealed/*` + `/cards/*` read routes.

**API test** (`tests/test_shop_assess_api.py`, I own): catalog-style fixture +
override `get_session` + monkeypatch `cardplatform.api.settings` (with +
without `listings_api_key`) + stub `EbayListingsProvider.fetch_listing_by_id` /
`fetch_sold_listings_by_query`. Cases: happy sealed, happy card, 422 on non-eBay
URL, 422 on blank, listing_unavailable (no key), listing_not_found (key set,
None), no-match still 200 with listing facts.

### 4. Frontend (Agent D — owns all frontend new + existing-file edits)

**`api/types.ts`** — add `ShopListing`, `ShopMatch`, `ShopDeal`,
`ShopAssessment` interfaces mirroring the wire models (null-for-missing,
source-on-every-figure). Import `AuthenticityOut`-equivalent (mirror the
existing `Authenticity`/`Consistency`/`ChecklistItem` types already in
`types.ts` — reuse them).

**`api/client.ts`** — add `getShopAssessment(url: string, limit = 6):
Promise<ShopAssessment>` modelled on `getSealedDeals`:
`URLSearchParams({ url, limit })`, GET `${BASE}/shop/assess`,
`expectJsonOrDetail` (so a 422 on a bad URL surfaces the backend detail).

**`components/ShopAssistant.tsx`** — submit-pattern (SealedDeals `run`, NOT
debounce — a URL is paste-then-submit). State: `url`, `loading`, `error`,
`data`. Form: `.deals-toolbar` with `input[type=search] aria-label="eBay
listing URL"` + submit button "Assess" (disabled while loading, label flips to
"Assessing…"). Render `ShopAssessment`:
- **Listing card** (`.deal-card` + `.shop-listing`): image (if present, `img`
  with `alt=title`), title, price (`formatMoney`), condition, seller, listing
  type, external link (`target="_blank" rel="noopener noreferrer"`).
- **Match line**: "Matched sealed product: {name}" / "Matched card: {name}
  ({set})" / "Couldn't match this listing to the catalog — showing listing
  facts only." (honest, no verdict when `kind==="none"`).
- **Deal** (`.shop-deal`): market (`formatMoney` + `source ·
  formatStaleness(source_updated_at)`), edge (`formatMoney`, colored
  `.deal-delta-over`/`.deal-delta-under`), verdict line: `is_deal` → "Below
  market — looks like a deal" ; edge>=0 but not deal → "At/below market but
  under the deal threshold" ; edge<0 → "Above market" ; edge null → "No market
  price to compare" (em dash, never $0). `market_unavailable` → "set a
  listings key to see the market"; `market_empty` → "no recent sold comps".
- **Authenticity** (card only, `.authenticity-*` reuse): caveat + consistency
  status (match=ok/mismatch=warn/unread & no_card=dim, NEVER red) + checklist
  with N/A items.
- **Caveat banner** (`.shop-caveat muted small`).
- **Honest empty states**: `listing_unavailable` → "Set
  CARDPLATFORM_LISTINGS_API_KEY to assess eBay listings."; `listing_not_found`
  → "Couldn't fetch this listing — check the URL."; error → "Couldn't assess
  this listing."; no-url-yet → "Paste an eBay listing URL to assess it.".

**Tests** (`__tests__/ShopAssistant.test.tsx`): `stubFetch` routing
`/shop/assess?` → assessment body. Cases: happy sealed (listing + deal-under +
match line), happy card (listing + authenticity match), no-match (listing facts
only, no deal), listing_unavailable ("set a listings key", no fabricated
market), listing_not_found, 422 surfaces detail (via `expectJsonOrDetail`),
authenticity unread (title without `NN/NNN`). Plus `__tests__/client.test.ts`
additions: the four canonical assertions for `getShopAssessment` (URL+params,
default limit 6, 422-detail, 200-body).

**Do-not-break**: the tab label is "Shop" (not "Scan"); the CTA is "Check a
listing" (verb phrase, distinct from every existing CTA). No new button named
"Scan" anywhere.

### 5. Integration I own (after the Workflow)

- `lib/route.ts`: add `"shop"` to `TabView` + `TAB_VIEWS` (after `catalog`,
  before `ledger` — or after `sets`; I'll place it after `catalog` so the
  shopping flow groups with catalog/prices). Add a `?view=shop` case to
  `__tests__/route.test.ts`.
- `components/AppShell.tsx`: `view === "shop" ? <PageTransition id="shop">
  <ShopAssistant /></PageTransition>` branch before the `more` fallback;
  `<TabButton label="Shop" glyph={<ShopGlyph />} />` in both bottom-nav +
  DesktopNav; `shop: "Shop"` in `TAB_TITLES`; `ShopGlyph` after `CatalogGlyph`
  (house idiom: `svg.nav-glyph`, stroke=currentColor, strokeWidth=1.8 — a
  shopping-bag or magnifier icon).
- `components/CommandPalette.tsx`: add `| "shop"` to local `Tab` union + `{ tab:
  "shop", label: "Go to Shop", hint: "eBay listing assessment" }` to
  `TAB_COMMANDS`.
- `components/Dashboard.tsx`: add `| "shop"` to local `Tab` union + a CTA
  `<button className="link" onClick={() => onNavigate("shop")}>Check a
  listing</button>` (after "Browse sealed catalog").
- `styles.css`: additive `.shop-*` classes (listing card image, deal verdict
  colors reuse `.deal-delta-over`/`.deal-delta-under`, caveat banner). No
  existing rule renamed/removed.
- `api.py` route + API test (above).

## Sacred constraints (held)

- `latest_price` / sold-comps-median only — never ad-hoc "the latest price".
- Staleness surfaced (`source` + `source_updated_at`) on every market figure.
- Honest empty states — em dash / "no market price" / "set a listings key" /
  "no recent sold comps", never `$0`, never fabricated.
- Providers degrade to `[]`/None, never raise.
- `func.lower(col).like(...)`, not `ilike`.
- No `data/` writes; 105-scan baseline untouched (zero recognition/detection
  code changed).
- Authenticity never a fake/real verdict (mirrors Phase 07).

## Test targets

- Backend: +1 provider test file, +1 assessor test file, +1 API test file
  (est. ~30 new tests → ~715 backend total).
- Frontend: +1 component test file, client.test additions (est. ~12 new → ~286
  frontend total).
- tsc clean, vite build clean, 105-scan baseline 0 regressions.

## Out of scope / follow-ups

- Multi-source URL support (TCGplayer/PriceCharting/cardmarket).
- Listing-image OCR for the printed number (today: title-extracted only).
- Sold-listing URL support (today: active listings only).
- Persisting assessments / a shopping history (today: on-demand, discarded).
- `CounterfeitLabel`-style accrual for a real learned detector (the honest
  accrual path, same gate as the grade predictor).