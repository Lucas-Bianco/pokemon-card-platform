# Deal Sniper / Rip-vs-Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join the 3b graded-price leg and the 3c listings leg into an evaluation that answers "is this active listing a deal — to rip (below raw market) or to flip (buy raw, grade, sell at PSA-10 comp)?" — with honest nulls whenever an edge input is missing.

**Architecture:** A read-only `DealEngine` computes per-listing rip/flip edges on demand from existing immutable snapshots via the existing never-ad-hoc services (`PriceService.latest_price`, `GradedPriceService.latest_graded`, `ListingsService.latest_listings`). The eBay `EbayListingsProvider` (3c, Browse-API, degrades to `[]`) is replaced with a Finding-API adapter (one `SECURITY-APPNAME` key, no OAuth) and its catalog lookup wired in, so listings — and therefore deals AND the 3c restock/new_listing/auction alerts — actually flow when a key is set. A new 6th bottom-nav **Deals** tab + CardDetail deal-score chips + a site Deals section.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / SQLite (`backend/.venv`), React 19 + TypeScript + Vite PWA (vitest), Next.js 15 static export → `docs/` for GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-03-deal-sniper-design.md` (read it — every contract below derives from it).

**Sacred constraints (hold every task):** no ad-hoc price resolution (only `latest_price` / `latest_graded` / `latest_listings`); snapshots immutable; the `DealEngine` is read-only (writes nothing); surface `source` + `source_updated_at` on every price; providers degrade to `[]`, never raise; honest empty states (never `$0`, never fabricate an edge); `func.lower(col).like` for text search; Python 3.12 via `backend/.venv`; never delete under `data/`; only edit within `C:\ClaudeKnowledge`; commit per task.

---

## File Structure

**Backend (new/modified):**
- Modify: `backend/src/cardplatform/prices/ebay_listings.py` — replace Browse-API `_search`/`_parse`/`_build_query` with Finding API; keep the never-raise discipline + `ListingQuote` construction.
- Modify: `backend/src/cardplatform/config.py` — `listings_base_url` default → Finding API endpoint; add `deal_rip_min_abs`, `deal_rip_min_pct`, `deal_flip_min_abs`.
- Modify: `backend/src/cardplatform/api.py` — wire `catalog` into `EbayListingsProvider(...)`; add `GET /cards/{card_id}/deals` + `GET /deals`.
- Modify: `backend/src/cardplatform/cli.py` — add `find-deals` command; wire `catalog` into the `check-alerts` provider.
- Create: `backend/src/cardplatform/deals/__init__.py`
- Create: `backend/src/cardplatform/deals/engine.py` — `DealEngine.assess` + `DealAssessment` dataclass.
- Create: `backend/src/cardplatform/deals/api_models.py` — Pydantic v2 wire models.
- Modify: `backend/tests/test_listings_provider.py` — rewrite for Finding-API shape.
- Create: `backend/tests/test_deal_engine.py`
- Create: `backend/tests/test_deals_api.py`
- Modify: `backend/tests/test_listings_api.py` — assert the catalog lookup is wired (keyword is name+number, not the slug).

**Frontend (new/modified):**
- Create: `frontend/src/components/Deals.tsx` — the 6th tab's deal feed.
- Modify: `frontend/src/components/AppShell.tsx` — add the Deals tab to bottom nav (6 tabs).
- Modify: `frontend/src/components/CardDetail.tsx` — per-listing deal-score chips via `getDeals`.
- Modify: `frontend/src/api/client.ts` — `getDeals`, `getDealsFeed`.
- Modify: `frontend/src/api/types.ts` — `DealAssessment`, `DealFeed`, `DealThresholds`.
- Create: `frontend/src/__tests__/Deals.test.tsx`
- Modify: `frontend/src/__tests__/CardDetail.test.tsx` — deal chip renders.

**Site (new/modified):**
- Create: `site/app/sections/Deals.tsx` — scroll-animated rip-vs-flip section.
- Modify: `site/app/sections/data.ts` — Phase 05 subtitle; wire Deals into `page.tsx`.
- Modify: `site/app/page.tsx` — render `<Deals/>` after `<Alerts/>`.

---

## Task 1: eBay Finding API adapter + config + catalog wiring

**Files:**
- Modify: `backend/src/cardplatform/prices/ebay_listings.py`
- Modify: `backend/src/cardplatform/config.py`
- Modify: `backend/src/cardplatform/api.py` (listings endpoint + catalog lookup helper)
- Modify: `backend/src/cardplatform/cli.py` (`check-alerts` catalog wiring)
- Modify: `backend/tests/test_listings_provider.py`
- Modify: `backend/tests/test_listings_api.py`

**Why:** The 3c `EbayListingsProvider` calls the Browse API (`item_summary/search`) with the key faked as a static bearer token — Browse needs a real OAuth client-credentials token, so it never returns listings in practice. The Finding API takes a single `SECURITY-APPNAME` (App ID) as a query param, no OAuth — Lucas's free eBay developer App ID works directly. The catalog lookup (card name + number) must be wired in so the keyword is `"Charizard ex 215"` not the `"base1-4"` slug (which returns nothing). This also unblocks the 3c restock/new_listing/auction alerts.

- [ ] **Step 1: Write the failing test for the Finding API shape**

Append to `backend/tests/test_listings_provider.py` (replace the existing parse tests — the Browse `itemSummaries` shape is gone). Keep the never-raise / no-key / transport-error tests (they don't depend on response shape); rewrite only the parse + URL/params assertions.

```python
# test_listings_provider.py — rewritten parse + request-shape tests
from unittest.mock import patch
from cardplatform.prices.ebay_listings import EbayListingsProvider
from cardplatform.config import Settings


def _settings_with_key():
    return Settings(listings_api_key="my-ebay-appid")


def _finding_payload(items):
    # Finding API wraps everything in single-element arrays.
    return {
        "findItemsByKeywordsResponse": [{
            "ack": ["Success"],
            "searchResult": [{"@count": str(len(items)), "item": items}],
        }]
    }


def test_no_key_returns_empty_without_network():
    p = EbayListingsProvider(Settings())  # no key
    assert p.fetch_listings("base1-4", "holofoil") == []


def test_finding_api_parses_fixed_price_item():
    payload = _finding_payload([{
        "itemId": ["123"],
        "title": ["Charizard ex 215 Paldean Fates Holo"],
        "viewItemURL": ["https://www.ebay.com/itm/123"],
        "sellingStatus": [{"currentPrice": [{"@currencyId": "USD", "__value__": "118.0"}]}],
        "listingInfo": [{"listingType": ["FixedPrice"], "endTime": ["2026-08-15T18:30:00.000Z"]}],
        "condition": [{"conditionDisplayName": ["Used"]}],
    }])
    p = EbayListingsProvider(_settings_with_key(), catalog=lambda c: ("Paldean Fates", "215", "Charizard ex"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        quotes = p.fetch_listings("base1-4", "holofoil")
    assert len(quotes) == 1
    q = quotes[0]
    assert q.listing_id == "123"
    assert q.price == 118.0 and q.currency == "USD"
    assert q.listing_type == "fixed_price"
    assert q.auction_end_at is None  # FixedPrice has no relevant end
    assert q.url == "https://www.ebay.com/itm/123"
    assert q.condition == "Used"
    assert q.source == "ebay"


def test_finding_api_parses_auction_item():
    payload = _finding_payload([{
        "itemId": ["7"],
        "title": ["Mew ex"],
        "viewItemURL": ["https://www.ebay.com/itm/7"],
        "sellingStatus": [{"currentPrice": [{"@currencyId": "USD", "__value__": "40.0"}]}],
        "listingInfo": [{"listingType": ["Auction"], "endTime": ["2026-08-15T18:30:00.000Z"]}],
    }])
    p = EbayListingsProvider(_settings_with_key(), catalog=lambda c: ("", "232", "Mew ex"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        quotes = p.fetch_listings("base1-232", "holofoil")
    assert quotes[0].listing_type == "auction"
    assert quotes[0].auction_end_at is not None
    assert quotes[0].auction_end_at.year == 2026


def test_finding_api_request_uses_appid_param_and_name_number_keyword():
    p = EbayListingsProvider(_settings_with_key(), catalog=lambda c: ("Paldean Fates", "215", "Charizard ex"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = _finding_payload([])
        p.fetch_listings("base1-4", "holofoil")
    _url, kw = mock_get.call_args
    assert kw["params"]["SECURITY-APPNAME"] == "my-ebay-appid"
    assert kw["params"]["OPERATION-NAME"] == "findItemsByKeywords"
    assert kw["params"]["keywords"] == "Charizard ex 215"  # name + number, NO set name


def test_finding_api_empty_searchresult_is_empty_list():
    payload = {"findItemsByKeywordsResponse": [{"ack": ["Success"], "searchResult": [{"@count": "0", "item": []}]}]}
    p = EbayListingsProvider(_settings_with_key())
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        assert p.fetch_listings("base1-4", "holofoil") == []


def test_finding_api_item_missing_price_is_skipped_not_fabricated():
    payload = _finding_payload([{"itemId": ["1"], "title": ["x"], "viewItemURL": ["u"],
                                 "listingInfo": [{"listingType": ["FixedPrice"]}]}])
    p = EbayListingsProvider(_settings_with_key())
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        assert p.fetch_listings("base1-4", "holofoil") == []


def test_finding_api_404_degrades_to_empty():
    p = EbayListingsProvider(Settings(http_max_attempts=1, listings_api_key="k"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 404
        mock_get.return_value.json.return_value = {}
        assert p.fetch_listings("base1-4", "holofoil") == []


def test_finding_api_bad_json_degrades_to_empty():
    p = EbayListingsProvider(Settings(http_max_attempts=1, listings_api_key="k"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.side_effect = ValueError("bad json")
        assert p.fetch_listings("base1-4", "holofoil") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_listings_provider.py -q`
Expected: FAIL (old Browse parse still in place; new assertions reference Finding shape).

- [ ] **Step 3: Update config.py**

In `backend/src/cardplatform/config.py`, change the listings block default and add the deal thresholds:

```python
    # Listings source (eBay Finding API findItemsByKeywords). Opt-in: when the
    # key is None (the default) the provider returns [] without touching the
    # network, so listings are simply unavailable until a key is configured.
    # The key is the eBay developer App ID (SECURITY-APPNAME) — one string, no
    # OAuth. Get one at developer.ebay.com -> My Apps -> create app -> App ID.
    listings_api_key: str | None = Field(default=None)
    listings_base_url: str = Field(default="https://svcs.ebay.com/services/search/FindingService/v1")
```

Add a new deals block (after the alerts block):

```python
    # --- deals (Phase 05 / rip-vs-flip) ---
    # Thresholds filter noise without manufacturing deals. A listing is a `rip`
    # when rip_edge >= deal_rip_min_abs AND >= deal_rip_min_pct * raw_market.
    # A listing is a `flip` when flip_edge_to_10 >= deal_flip_min_abs (grading
    # fee + meaningful profit). Edges are indicative leads, not arbitrage.
    deal_rip_min_abs: float = Field(default=2.0)
    deal_rip_min_pct: float = Field(default=0.10)
    deal_flip_min_abs: float = Field(default=20.0)
```

- [ ] **Step 4: Rewrite ebay_listings.py `_build_query`, `_search`, `_parse`**

Replace the module docstring's Browse references with Finding API. Keep `_TerminalHttpError`, `_CatalogLookup`, the constructor, `fetch_listings` (unchanged — it already returns `[]` without a key, calls `_build_query` → `_search` → `_parse`, degrades on parse). Replace the three methods:

```python
    def _build_query(self, card_id: str) -> str:
        """Build the eBay search query: card name + number (NO set name — eBay
        keyword search over-matches on set names). Falls back to the raw card_id
        slug when no catalog callable is wired (the 3c default — returns noisy
        or empty results, but never raises). Keyword search is best-effort —
        treat listings as leads to verify, not authoritative matches."""
        if self.catalog is not None:
            try:
                meta = self.catalog(card_id)
            except Exception as exc:  # noqa: BLE001 — catalog is app-supplied
                logger.warning("ebay catalog lookup failed for %s: %s", card_id, exc)
                meta = None
            if meta is not None:
                _set_name, number, card_name = meta
                return f"{card_name} {number}".strip()
        return card_id

    def _search(self, query: str) -> dict[str, Any] | None:
        """GET the eBay Finding API, retrying transport/5xx/429 only.

        Mirrors the 3c discipline: 404/401 raise _TerminalHttpError (one
        attempt); 5xx/429/transport return None and tenacity retries; 200 with
        bad JSON is terminal (one attempt); RetryError degrades to None.
        SECURITY-APPNAME is a query param (NOT an auth header) — the Finding
        API uses the App ID directly, no OAuth token.
        """
        url = self.settings.listings_base_url
        params = {
            "OPERATION-NAME": "findItemsByKeywords",
            "SERVICE-VERSION": "1.13.0",
            "SECURITY-APPNAME": self.settings.listings_api_key,
            "RESPONSE-DATA-FORMAT": "JSON",
            "REST-PAYLOAD": "",
            "GLOBAL-ID": "EBAY-US",
            "keywords": query,
            "paginationInput.entriesPerPage": "20",
        }

        @retry(
            stop=stop_after_attempt(self.settings.http_max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_result(lambda r: r is None),
        )
        def _attempt() -> dict[str, Any] | None:
            try:
                response = httpx.get(
                    url, params=params, timeout=self.settings.http_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                logger.warning("ebay listings transport error for %r: %s", query, exc)
                return None
            if response.status_code == 200:
                try:
                    return response.json()
                except (httpx.DecodingError, ValueError) as exc:
                    logger.warning("ebay listings bad JSON for %r: %s", query, exc)
                    raise _TerminalHttpError(response.status_code) from exc
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning("ebay listings HTTP %s for %r (retryable)", response.status_code, query)
                return None
            logger.warning("ebay listings HTTP %s for %r (terminal)", response.status_code, query)
            raise _TerminalHttpError(response.status_code)

        try:
            return _attempt()
        except _TerminalHttpError:
            return None
        except RetryError:
            logger.error("ebay listings gave up for %r after %s attempts", query, self.settings.http_max_attempts)
            return None

    @staticmethod
    def _parse(card_id: str, variant: str, payload: dict[str, Any]) -> list[ListingQuote]:
        """Map eBay Finding API `findItemsByKeywordsResponse.searchResult.item`
        -> ListingQuotes.

        The Finding API is XML-first; serialized to JSON it wraps EVERY field
        in a single-element array, so each access is `[0]`. For each item:
        listing_id from itemId, price/currency from sellingStatus.currentPrice
        (skip if present-but-unparseable — never fabricate), url from
        viewItemURL, listing_type from listingInfo.listingType
        (Auction/AuctionWithBIN -> "auction", else "fixed_price"),
        auction_end_at from listingInfo.endTime (tz-aware UTC, or None),
        condition from condition.conditionDisplayName. source="ebay";
        source_updated_at None (Finding API exposes no per-listing updated
        stamp; the service normalizes None -> "" for dedupe). Skip rows
        missing itemId — never fabricate.
        """
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        resp = payload.get("findItemsByKeywordsResponse")
        if not isinstance(resp, list) or not resp:
            return []
        search = _first(resp[0], "searchResult")
        if not isinstance(search, list) or not search:
            return []
        items = search[0].get("item")
        if not isinstance(items, list):
            return []

        quotes: list[ListingQuote] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            listing_id = _first(item, "itemId")
            if not listing_id:
                continue

            price: float | None = None
            currency: str | None = None
            selling = _first(item, "sellingStatus")
            if isinstance(selling, dict):
                price_block = _first(selling, "currentPrice")
                if isinstance(price_block, dict):
                    currency = price_block.get("@currencyId")
                    raw_value = price_block.get("__value__")
                    if raw_value is not None:
                        try:
                            price = float(raw_value)
                        except (TypeError, ValueError):
                            continue  # price present but unparseable — skip, don't fake

            listing_info = _first(item, "listingInfo")
            ltype_raw = _first(listing_info, "listingType") if isinstance(listing_info, dict) else None
            listing_type = "auction" if (isinstance(ltype_raw, str) and ltype_raw.startswith("Auction")) else "fixed_price"
            auction_end_at = _parse_iso(_first(listing_info, "endTime")) if isinstance(listing_info, dict) else None

            condition = None
            cond_block = _first(item, "condition")
            if isinstance(cond_block, dict):
                condition = _first(cond_block, "conditionDisplayName")

            quotes.append(
                ListingQuote(
                    card_id=card_id, variant=variant, listing_id=str(listing_id),
                    title=_first(item, "title"), price=price, currency=currency,
                    listing_type=listing_type, auction_end_at=auction_end_at,
                    url=_first(item, "viewItemURL"), condition=condition,
                    source="ebay", source_updated_at=None,
                )
            )
        return quotes
```

Keep the `_parse_iso` helper unchanged. Update the module docstring to describe Finding API + the App-ID auth (replace the Browse/OAuth-bearer paragraphs).

- [ ] **Step 5: Add a catalog lookup helper in api.py and wire it into the listings endpoint**

In `backend/src/cardplatform/api.py`, near the other helpers (e.g. after `_require_card`), add:

```python
def _catalog_lookup(session: Session):
    """Build an EbayListingsProvider catalog callable: card_id -> (set_name,
    number, card_name) | None. Resolves the catalog row + its set so the eBay
    keyword is the card's real name + number (not the 'base1-4' slug, which
    returns nothing). Returns None for an unknown card (provider falls back to
    the slug — never raises)."""
    from cardplatform.db.models import Card
    def _lookup(card_id: str) -> tuple[str, str, str] | None:
        card = session.get(Card, card_id)
        if card is None:
            return None
        set_name = card.card_set.name if card.card_set is not None else ""
        return (set_name, card.number, card.name)
    return _lookup
```

Change the listings endpoint to wire it:

```python
        service = ListingsService(session, EbayListingsProvider(catalog=_catalog_lookup(session)))
```

- [ ] **Step 6: Wire the catalog lookup into cli.py `check-alerts`**

In `backend/src/cardplatform/cli.py` `check_alerts`, replace the provider construction:

```python
    from cardplatform.alerts.engine import AlertEngine
    from cardplatform.alerts.notify import NotificationService
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService
    from cardplatform.api import _catalog_lookup

    db = Database()
    db.create_all()

    with db.session() as session:
        engine = AlertEngine(
            session,
            ListingsService(session, EbayListingsProvider(catalog=_catalog_lookup(session))),
            NotificationService(session, db.settings),
            db.settings,
        )
        n = engine.check_alerts()
    print(f"{n} alerts fired")
    return 0
```

(Importing `_catalog_lookup` from `api.py` is fine — it's a plain function, and `cli.py` already does lazy imports inside the handler to avoid import cycles.)

- [ ] **Step 7: Add a listings-api test asserting the keyword is name+number**

In `backend/tests/test_listings_api.py`, add (or extend the existing refresh-listings test) a test that monkeypatches `EbayListingsProvider.fetch_listings` to capture the query the provider builds, and asserts it is the card's `name + number`, not the slug. Use a known catalog card (e.g. `base1-4` → name "Charizard ex", number "4" — confirm the exact name/number from the live DB in the test setup, or assert it contains the number and is not equal to `"base1-4"`).

```python
def test_listings_endpoint_wires_catalog_lookup(app_client, monkeypatch):
    # The provider must build the eBay keyword from the card's name + number,
    # not the raw 'base1-4' slug. Capture the query via the catalog callable.
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    captured = {}
    orig = EbayListingsProvider._build_query
    def spy(self, card_id):
        q = orig(self, card_id)
        captured["query"] = q
        return q
    monkeypatch.setattr(EbayListingsProvider, "_build_query", spy)
    # force fetch_listings to return [] so the endpoint completes without network
    monkeypatch.setattr(EbayListingsProvider, "fetch_listings", lambda self, c, v: [])
    r = app_client.post("/cards/base1-4/listings?variant=holofoil")
    assert r.status_code == 200
    assert captured["query"] != "base1-4"          # not the slug
    assert captured["query"].endswith("4")         # ends with the card number
```

(Adjust the existing `app_client` fixture name to match the test file's actual fixture.)

- [ ] **Step 8: Run the full backend suite; confirm green**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (443 + new provider tests, 0 regressions).

- [ ] **Step 9: Commit**

```bash
git add backend/src/cardplatform/prices/ebay_listings.py backend/src/cardplatform/config.py \
        backend/src/cardplatform/api.py backend/src/cardplatform/cli.py \
        backend/tests/test_listings_provider.py backend/tests/test_listings_api.py
git commit -m "feat(deals): eBay Finding API adapter + catalog wiring (T1)

Replace the 3c Browse-API adapter (which faked a static bearer token and
never returned listings — Browse needs real OAuth) with the Finding API:
one SECURITY-APPNAME (App ID) query param, no OAuth. Parse the
array-wrapped Finding JSON shape. Build the keyword from the card's
name + number via a catalog lookup wired into the API + CLI paths (was
the 'base1-4' slug, which returned nothing). Also unblocks the 3c
restock/new_listing/auction alerts. Add deal threshold settings."
```

---

## Task 2: DealEngine + DealAssessment

**Files:**
- Create: `backend/src/cardplatform/deals/__init__.py`
- Create: `backend/src/cardplatform/deals/engine.py`
- Create: `backend/tests/test_deal_engine.py`

**Why:** The read-only core. Computes rip/flip edges per listing from the three never-ad-hoc services. Writes nothing — deals are computed on demand so they never go stale in storage and the sacred-snapshot rule holds.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_deal_engine.py`:

```python
from datetime import datetime, timezone
from cardplatform.deals.engine import DealEngine, DealAssessment
from cardplatform.db.models import PriceSnapshot, GradedPriceSnapshot, ListingSnapshot


def _add_price(session, card_id, variant, market, source="tcgplayer", stamp="2026-08-01"):
    session.add(PriceSnapshot(card_id=card_id, source=source, variant=variant,
                             market=market, source_updated_at=stamp))
    session.commit()


def _add_graded(session, card_id, variant, grade, market, grader="PSA", stamp="2026-08-01"):
    session.add(GradedPriceSnapshot(card_id=card_id, grader=grader, grade=grade, variant=variant,
                                    market=market, source="pkmnprices", source_updated_at=stamp))
    session.commit()


def _add_listing(session, card_id, variant, listing_id, price, listing_type="fixed_price",
                 auction_end_at=None, fetched_at=None):
    session.add(ListingSnapshot(card_id=card_id, variant=variant, source="ebay",
                                listing_id=listing_id, title="t", price=price,
                                currency="USD", listing_type=listing_type,
                                auction_end_at=auction_end_at, url="u", condition="Raw",
                                source_updated_at="", fetched_at=fetched_at or datetime(2026, 8, 2, tzinfo=timezone.utc)))
    session.commit()


def test_rip_edge_below_market_is_flagged(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    _add_listing(session, "base1-4", "holofoil", "L1", 100.0)  # 20 below market
    engine = DealEngine(session, db.settings)
    deals = engine.assess("base1-4", "holofoil")
    assert len(deals) == 1
    d = deals[0]
    assert d.rip_edge == 20.0
    assert d.is_rip is True                      # 20 >= 2.0 and 20 >= 0.10*120=12
    assert d.raw_market.price == 120.0


def test_small_rip_below_threshold_not_flagged(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    _add_listing(session, "base1-4", "holofoil", "L1", 117.0)  # 3 below, 2.5% — under pct threshold
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.rip_edge == 3.0
    assert d.is_rip is False                     # 3 < 12 (10% of 120)


def test_flip_edge_to_10_with_grading_fee(session, db):
    # fee 25; listing 100; psa10 200 -> flip_to_10 = 200-100-25 = 75
    _add_graded(session, "base1-4", "holofoil", 10, 200.0)
    _add_graded(session, "base1-4", "holofoil", 9, 150.0)
    _add_listing(session, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.flip_edge_to_10 == 75.0
    assert d.flip_edge_to_9 == 25.0
    assert d.is_flip is True                     # 75 >= 20


def test_no_raw_market_nulls_rip_edge(session, db):
    _add_listing(session, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.rip_edge is None
    assert d.raw_market is None
    assert d.is_rip is False


def test_no_graded_comps_nulls_flip_edges(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    _add_listing(session, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.flip_edge_to_9 is None
    assert d.flip_edge_to_10 is None
    assert d.psa9_comp is None and d.psa10_comp is None
    assert d.is_flip is False


def test_no_listings_returns_empty(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    engine = DealEngine(session, db.settings)
    assert engine.assess("base1-4", "holofoil") == []


def test_deals_ranked_by_score_desc_nulls_last(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    _add_graded(session, "base1-4", "holofoil", 10, 200.0)
    _add_listing(session, "base1-4", "holofoil", "big", 80.0)    # rip 40, flip 95 -> score 95
    _add_listing(session, "base1-4", "holofoil", "small", 115.0) # rip 5  -> score 5
    engine = DealEngine(session, db.settings)
    deals = engine.assess("base1-4", "holofoil")
    assert [d.listing_id for d in deals] == ["big", "small"]


def test_unpriced_listing_kept_with_null_edges(session, db):
    _add_price(session, "base1-4", "holofoil", 120.0)
    _add_listing(session, "base1-4", "holofoil", "L1", None)  # price None
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.listing_price is None
    assert d.rip_edge is None and d.flip_edge_to_10 is None


def test_thresholds_field_in_assessment(session, db):
    _add_listing(session, "base1-4", "holofoil", "L1", 100.0)
    engine = DealEngine(session, db.settings)
    d = engine.assess("base1-4", "holofoil")[0]
    assert d.thresholds.deal_rip_min_abs == db.settings.deal_rip_min_abs
```

(Confirm the `session` / `db` fixture names match `backend/tests/conftest.py`; adjust if they differ.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_deal_engine.py -q`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement the engine**

Create `backend/src/cardplatform/deals/__init__.py` (empty).

Create `backend/src/cardplatform/deals/engine.py`:

```python
"""DealEngine — rip-vs-flip evaluation of active listings (Phase 05).

READ-ONLY. Computes per-listing rip/flip edges on demand from the latest
immutable snapshots via the three never-ad-hoc services (PriceService,
GradedPriceService, ListingsService). Writes nothing — deals are derived from
the newest snapshots each call, so they never go stale in storage and the
sacred-snapshot rule holds. Missing inputs null the edge they feed — never a
fabricated $0, never a fake profit.

rip_edge        = raw_market.price − listing.price
flip_edge_to_9  = psa9.market  − listing.price − grading_fee
flip_edge_to_10 = psa10.market − listing.price − grading_fee
deal_score      = max(rip_edge or 0, flip_edge_to_10 or 0)   # ranking; nulls last

A listing is `is_rip` iff rip_edge >= deal_rip_min_abs AND
rip_edge >= deal_rip_min_pct * raw_market.price. A listing is `is_flip` iff
flip_edge_to_10 >= deal_flip_min_abs. Edges are indicative leads — eBay
keyword listings carry seller-mislabel noise; the UI says "investigate before
buying". This engine never decides "buy" — it surfaces candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.graded_service import GradedPriceService
from cardplatform.prices.listings_service import ListingsService
from cardplatform.prices.service import PriceService


@dataclass(frozen=True)
class _PricePoint:
    price: float
    source: str
    source_updated_at: str


@dataclass(frozen=True)
class _Thresholds:
    deal_rip_min_abs: float
    deal_rip_min_pct: float
    deal_flip_min_abs: float


@dataclass(frozen=True)
class DealAssessment:
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: object | None          # datetime | None
    fetched_at: object                       # datetime
    raw_market: _PricePoint | None
    rip_edge: float | None
    psa9_comp: _PricePoint | None
    psa10_comp: _PricePoint | None
    flip_edge_to_9: float | None
    flip_edge_to_10: float | None
    grading_fee: float
    deal_score: float | None
    is_rip: bool
    is_flip: bool
    thresholds: _Thresholds


class DealEngine:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        price_service: PriceService | None = None,
        graded_service: GradedPriceService | None = None,
        listings_service: ListingsService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or default_settings
        self.price_service = price_service or PriceService(session)
        self.graded_service = graded_service or GradedPriceService(session)
        self.listings_service = listings_service or ListingsService(session)

    def assess(self, card_id: str, variant: str) -> list[DealAssessment]:
        """Ranked deals for one (card_id, variant). Empty list if no listings.
        Never raises — missing services inputs surface as honest null edges."""
        raw = self.price_service.latest_price(card_id, variant)
        raw_point = (
            _PricePoint(raw.market, raw.source, raw.source_updated_at)
            if raw is not None and raw.market is not None
            else None
        )
        psa9 = self.graded_service.latest_graded(card_id, variant, 9.0, "PSA")
        psa9_point = (
            _PricePoint(psa9.market, psa9.source, psa9.source_updated_at)
            if psa9 is not None and psa9.market is not None
            else None
        )
        psa10 = self.graded_service.latest_graded(card_id, variant, 10.0, "PSA")
        psa10_point = (
            _PricePoint(psa10.market, psa10.source, psa10.source_updated_at)
            if psa10 is not None and psa10.market is not None
            else None
        )
        fee = self.settings.grading_fee
        th = _Thresholds(
            self.settings.deal_rip_min_abs,
            self.settings.deal_rip_min_pct,
            self.settings.deal_flip_min_abs,
        )

        listings = self.listings_service.latest_listings(card_id, variant)
        assessments: list[DealAssessment] = []
        for row in listings:
            price = row.price
            rip_edge = (
                raw_point.price - price
                if raw_point is not None and price is not None
                else None
            )
            flip9 = (
                psa9_point.price - price - fee
                if psa9_point is not None and price is not None
                else None
            )
            flip10 = (
                psa10_point.price - price - fee
                if psa10_point is not None and price is not None
                else None
            )
            is_rip = (
                rip_edge is not None
                and rip_edge >= th.deal_rip_min_abs
                and rip_edge >= th.deal_rip_min_pct * raw_point.price
            )
            is_flip = flip10 is not None and flip10 >= th.deal_flip_min_abs
            score = (
                max(rip_edge or 0.0, flip10 or 0.0)
                if (rip_edge is not None or flip10 is not None)
                else None
            )
            assessments.append(
                DealAssessment(
                    listing_id=row.listing_id, title=row.title, listing_price=price,
                    currency=row.currency, url=row.url, condition=row.condition,
                    listing_type=row.listing_type, auction_end_at=row.auction_end_at,
                    fetched_at=row.fetched_at, raw_market=raw_point, rip_edge=rip_edge,
                    psa9_comp=psa9_point, psa10_comp=psa10_point,
                    flip_edge_to_9=flip9, flip_edge_to_10=flip10, grading_fee=fee,
                    deal_score=score, is_rip=is_rip, is_flip=is_flip, thresholds=th,
                )
            )

        # deal_score desc, nulls last.
        assessments.sort(
            key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0))
        )
        return assessments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_deal_engine.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the full backend suite; confirm no regressions**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/deals/__init__.py backend/src/cardplatform/deals/engine.py \
        backend/tests/test_deal_engine.py
git commit -m "feat(deals): read-only DealEngine rip/flip edges (T2)

Per-listing rip_edge (raw market - listing price) and flip_edge_to_9/10
(graded comp - listing price - grading fee) from the three never-ad-hoc
services. Writes nothing — deals are derived from the newest snapshots
each call so they never go stale in storage. Missing inputs null the
edge they feed; thresholds filter noise without manufacturing deals;
ranked by deal_score desc, nulls last."
```

---

## Task 3: Deal API + find-deals CLI

**Files:**
- Create: `backend/src/cardplatform/deals/api_models.py`
- Modify: `backend/src/cardplatform/api.py` (two endpoints)
- Modify: `backend/src/cardplatform/cli.py` (`find-deals`)
- Create: `backend/tests/test_deals_api.py`

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/test_deals_api.py`:

```python
def test_deals_endpoint_returns_ranked_deals(app_client, session, db):
    from cardplatform.db.models import PriceSnapshot, GradedPriceSnapshot, ListingSnapshot
    session.add(PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil",
                              market=120.0, source_updated_at="2026-08-01"))
    session.add(GradedPriceSnapshot(card_id="base1-4", grader="PSA", grade=10.0,
                                    variant="holofoil", market=200.0, source="pkmnprices",
                                    source_updated_at="2026-08-01"))
    session.add(ListingSnapshot(card_id="base1-4", variant="holofoil", source="ebay",
                                listing_id="L1", title="Charizard", price=80.0, currency="USD",
                                listing_type="fixed_price", url="u", condition="Raw",
                                source_updated_at=""))
    session.commit()
    r = app_client.get("/cards/base1-4/deals?variant=holofoil")
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is False
    d = body["deals"][0]
    assert d["listing_id"] == "L1"
    assert d["rip_edge"] == 40.0
    assert d["flip_edge_to_10"] == 95.0
    assert d["is_rip"] is True and d["is_flip"] is True
    assert d["raw_market"]["price"] == 120.0
    assert d["raw_market"]["source"] == "tcgplayer"
    assert "thresholds" in body


def test_deals_endpoint_unknown_card_404(app_client):
    r = app_client.get("/cards/nope-1/deals")
    assert r.status_code == 404


def test_deals_endpoint_listings_unavailable_when_no_key(app_client, session, monkeypatch):
    # No ListingSnapshot rows AND no listings_api_key configured -> unavailable.
    from cardplatform.config import settings
    monkeypatch.setattr(settings, "listings_api_key", None)
    r = app_client.get("/cards/base1-4/deals?variant=holofoil")
    assert r.status_code == 200
    assert r.json()["listings_unavailable"] is True
    assert r.json()["deals"] == []


def test_deals_endpoint_listings_empty_when_key_set_no_rows(app_client, session, db, monkeypatch):
    from cardplatform.config import settings
    monkeypatch.setattr(settings, "listings_api_key", "an-app-id")
    r = app_client.get("/cards/base1-4/deals?variant=holofoil")
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is True
    assert body["deals"] == []


def test_deals_feed_defaults_to_watched_cards(app_client, session, db):
    from cardplatform.db.models import Watch, PriceSnapshot, ListingSnapshot
    session.add(Watch(card_id="base1-4", alert_type="price_target", target_price=100.0, active=True))
    session.add(PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil",
                              market=120.0, source_updated_at="2026-08-01"))
    session.add(ListingSnapshot(card_id="base1-4", variant="holofoil", source="ebay",
                                listing_id="L1", title="c", price=100.0, currency="USD",
                                listing_type="fixed_price", url="u", condition="Raw",
                                source_updated_at=""))
    session.commit()
    r = app_client.get("/deals")
    assert r.status_code == 200
    body = r.json()
    assert any(d["listing_id"] == "L1" for d in body["deals"])


def test_deals_feed_explicit_card_ids(app_client, session, db):
    from cardplatform.db.models import PriceSnapshot, ListingSnapshot
    session.add(PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil",
                              market=120.0, source_updated_at="2026-08-01"))
    session.add(ListingSnapshot(card_id="base1-4", variant="holofoil", source="ebay",
                                listing_id="L1", title="c", price=100.0, currency="USD",
                                listing_type="fixed_price", url="u", condition="Raw",
                                source_updated_at=""))
    session.commit()
    r = app_client.get("/deals?card_ids=base1-4&limit=5")
    assert r.status_code == 200
    assert len(r.json()["deals"]) == 1
```

(Adjust fixture names to match `conftest.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_deals_api.py -q`
Expected: FAIL (endpoints don't exist).

- [ ] **Step 3: Implement the Pydantic wire models**

Create `backend/src/cardplatform/deals/api_models.py`:

```python
"""Pydantic wire models for the Phase 05 deals API.

Mirrors the rest of api.py: Pydantic v2 with from_attributes=True. Every
nullable field surfaces as None — a missing edge input is never a fabricated
$0. The engine's internal _PricePoint / _Thresholds dataclasses are mapped
here to flat nested objects the frontend can read.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PricePointOut(BaseModel):
    price: float
    source: str
    source_updated_at: str


class ThresholdsOut(BaseModel):
    deal_rip_min_abs: float
    deal_rip_min_pct: float
    deal_flip_min_abs: float


class DealAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    fetched_at: datetime
    raw_market: PricePointOut | None
    rip_edge: float | None
    psa9_comp: PricePointOut | None
    psa10_comp: PricePointOut | None
    flip_edge_to_9: float | None
    flip_edge_to_10: float | None
    grading_fee: float
    deal_score: float | None
    is_rip: bool
    is_flip: bool


class DealsResponse(BaseModel):
    card_id: str | None = None
    variant: str | None = None
    listings_unavailable: bool
    listings_empty: bool
    deals: list[DealAssessmentOut]
    thresholds: ThresholdsOut
```

- [ ] **Step 4: Implement the two endpoints in api.py**

In `backend/src/cardplatform/api.py`, add the import near the other deals/alerts imports:

```python
from cardplatform.deals.engine import DealEngine
from cardplatform.deals.api_models import DealAssessmentOut, DealsResponse, ThresholdsOut
```

Add a small serializer (near `_require_card`):

```python
def _deal_out(a) -> DealAssessmentOut:
    def _pp(p):
        return {"price": p.price, "source": p.source, "source_updated_at": p.source_updated_at} if p else None
    return DealAssessmentOut(
        listing_id=a.listing_id, title=a.title, listing_price=a.listing_price,
        currency=a.currency, url=a.url, condition=a.condition, listing_type=a.listing_type,
        auction_end_at=a.auction_end_at, fetched_at=a.fetched_at,
        raw_market=_pp(a.raw_market), rip_edge=a.rip_edge,
        psa9_comp=_pp(a.psa9_comp), psa10_comp=_pp(a.psa10_comp),
        flip_edge_to_9=a.flip_edge_to_9, flip_edge_to_10=a.flip_edge_to_10,
        grading_fee=a.grading_fee, deal_score=a.deal_score, is_rip=a.is_rip, is_flip=a.is_flip,
    )
```

Add the endpoints (after the listings endpoint, before the push block):

```python
    # --------------------------------------------------------------- deals
    @app.get("/cards/{card_id}/deals", response_model=DealsResponse)
    def card_deals(
        card_id: str,
        variant: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> DealsResponse:
        """Rip-vs-flip deals for one card. Honest empty states: when no
        listings_api_key is configured, listings_unavailable is True; when a
        key is set but no listings exist, listings_empty is True. Missing
        raw/graded inputs null the edges — never a fake $0. Unknown card 404."""
        _require_card(session, card_id)
        v = variant or ""
        engine = DealEngine(session, settings)
        assessments = engine.assess(card_id, v)
        return DealsResponse(
            card_id=card_id, variant=v or None,
            listings_unavailable=settings.listings_api_key is None,
            listings_empty=(settings.listings_api_key is not None and not assessments),
            deals=[_deal_out(a) for a in assessments],
            thresholds=ThresholdsOut(
                deal_rip_min_abs=settings.deal_rip_min_abs,
                deal_rip_min_pct=settings.deal_rip_min_pct,
                deal_flip_min_abs=settings.deal_flip_min_abs,
            ),
        )

    @app.get("/deals", response_model=DealsResponse)
    def deals_feed(
        card_ids: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        session: Session = Depends(get_session),
    ) -> DealsResponse:
        """Cross-card deal feed. card_ids (CSV) defaults to the user's active
        watched cards. Assesses each, merges, ranks by deal_score desc, truncates
        to limit. Honest per-card flags merge into the overall flags (unavailable
        if NO card had a key; empty if every card had a key but none had listings)."""
        ids: list[str]
        if card_ids:
            ids = [c.strip() for c in card_ids.split(",") if c.strip()]
        else:
            rows = session.scalars(
                select(Watch.card_id).where(Watch.active.is_(True), Watch.card_id.is_not(None))
            ).all()
            ids = sorted({r for r in rows})
        engine = DealEngine(session, settings)
        merged: list = []
        any_key = settings.listings_api_key is not None
        any_listing = False
        for cid in ids:
            # variant unknown per-card in the feed — assess the empty variant,
            # which matches the latest_listings "" variant rows most listings use.
            assessments = engine.assess(cid, "")
            if assessments:
                any_listing = True
            merged.extend(assessments)
        merged.sort(key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0)))
        return DealsResponse(
            card_id=None, variant=None,
            listings_unavailable=not any_key,
            listings_empty=any_key and not any_listing,
            deals=[_deal_out(a) for a in merged[:limit]],
            thresholds=ThresholdsOut(
                deal_rip_min_abs=settings.deal_rip_min_abs,
                deal_rip_min_pct=settings.deal_rip_min_pct,
                deal_flip_min_abs=settings.deal_flip_min_abs,
            ),
        )
```

Ensure `Watch` is imported in `api.py` (it already is from 3c).

- [ ] **Step 5: Add the `find-deals` CLI**

In `backend/src/cardplatform/cli.py`, add the handler (after `check_alerts`):

```python
def find_deals(args: argparse.Namespace) -> int:
    """Assess one card's active listings for rip/flip deals and print them.

    Mirrors the /cards/{id}/deals endpoint: builds a DealEngine from the latest
    snapshots and prints ranked deals (price, rip edge, flip-to-10, flags, url).
    Honest messages for the no-key / no-listings / no-market cases — never
    fabricates an edge."""
    from cardplatform.deals.engine import DealEngine
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService
    from cardplatform.api import _catalog_lookup

    db = Database()
    db.create_all()
    variant = args.variant or ""

    with db.session() as session:
        # Refresh listings first so the assessment is against the newest fetch.
        if db.settings.listings_api_key:
            ListingsService(session, EbayListingsProvider(catalog=_catalog_lookup(session))).refresh_listings(
                args.card_id, variant
            )
        engine = DealEngine(session, db.settings)
        deals = engine.assess(args.card_id, variant)

    if db.settings.listings_api_key is None:
        print("No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY (eBay App ID) to find deals.")
        return 0
    if not deals:
        print(f"No active listings for {args.card_id} (variant={variant or 'none'}).")
        return 0
    print(f"Deals for {args.card_id} (variant={variant or 'none'}):")
    for d in deals:
        rip = f"${d.rip_edge:.2f}" if d.rip_edge is not None else "—"
        flip = f"${d.flip_edge_to_10:.2f}" if d.flip_edge_to_10 is not None else "—"
        flags = ("RIP " if d.is_rip else "") + ("FLIP" if d.is_flip else "")
        flags = flags or "—"
        price = f"${d.listing_price:.2f}" if d.listing_price is not None else "—"
        print(f"  {price:>8}  rip={rip:>8}  flip10={flip:>8}  [{flags}]  {d.url}")
    return 0
```

Register the subparser in `build_parser`:

```python
    find = subparsers.add_parser(
        "find-deals",
        help="Assess one card's active listings for rip/flip deals (Phase 05).",
    )
    find.add_argument("card_id", metavar="CARD_ID", help="e.g. base1-4")
    find.add_argument("--variant", default="", help="e.g. holofoil (default empty)")
    find.set_defaults(handler=find_deals)
```

- [ ] **Step 6: Run the API + CLI tests**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest backend/tests/test_deals_api.py -q`
Expected: PASS (6 tests).

Smoke the CLI (no key in this env → honest "no key" message):
Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m cardplatform find-deals base1-4`
Expected: `No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY (eBay App ID) to find deals.`

- [ ] **Step 7: Run the full backend suite; confirm green**

Run: `cd C:\ClaudeKnowledge && backend/.venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/cardplatform/deals/api_models.py backend/src/cardplatform/api.py \
        backend/src/cardplatform/cli.py backend/tests/test_deals_api.py
git commit -m "feat(deals): /cards/{id}/deals + /deals feed + find-deals CLI (T3)

Two endpoints (per-card ranked deals; cross-card feed defaulting to the
watchlist) + a find-deals CLI. Honest listings_unavailable / listings_empty
flags; missing raw/graded inputs null the edges. DealEngine stays
read-only; thresholds surfaced in the response."
```

---

## Task 4: Frontend — Deals tab + CardDetail deal chips

**Files:**
- Create: `frontend/src/components/Deals.tsx`
- Modify: `frontend/src/components/AppShell.tsx` (6th tab)
- Modify: `frontend/src/components/CardDetail.tsx` (deal-score chips)
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/__tests__/Deals.test.tsx`
- Modify: `frontend/src/__tests__/CardDetail.test.tsx`

**Pattern note:** Match the 3c component style (honest empty states, `expectJsonOrDetail`, no fabricated data, `formatMoney`'s `toFixed(2)` no-thousands-comma). Read the existing `AlertsFeed.tsx` / `WatchCardSheet.tsx` / `CardDetail.tsx` before writing — they set the patterns for fetch-on-mount, debounced search, honest-empty rendering, and the listings section you'll add chips to.

- [ ] **Step 1: Add the API client + types**

In `frontend/src/api/types.ts`:

```ts
export interface DealPricePoint { price: number; source: string; source_updated_at: string; }
export interface DealThresholds { deal_rip_min_abs: number; deal_rip_min_pct: number; deal_flip_min_abs: number; }
export interface DealAssessment {
  listing_id: string; title: string | null; listing_price: number | null;
  currency: string | null; url: string | null; condition: string | null;
  listing_type: string | null; auction_end_at: string | null; fetched_at: string;
  raw_market: DealPricePoint | null; rip_edge: number | null;
  psa9_comp: DealPricePoint | null; psa10_comp: DealPricePoint | null;
  flip_edge_to_9: number | null; flip_edge_to_10: number | null;
  grading_fee: number; deal_score: number | null; is_rip: boolean; is_flip: boolean;
}
export interface DealsResponse {
  card_id: string | null; variant: string | null;
  listings_unavailable: boolean; listings_empty: boolean;
  deals: DealAssessment[]; thresholds: DealThresholds;
}
```

In `frontend/src/api/client.ts` (mirror `getAlerts` / `getWatches`):

```ts
export async function getDeals(cardId: string, variant?: string): Promise<DealsResponse> {
  const q = variant ? `?variant=${encodeURIComponent(variant)}` : "";
  return expectJsonOrDetail(fetch(`${API_BASE}/cards/${encodeURIComponent(cardId)}/deals${q}`));
}
export async function getDealsFeed(cardIds?: string[], limit = 20): Promise<DealsResponse> {
  const params = new URLSearchParams();
  if (cardIds && cardIds.length) params.set("card_ids", cardIds.join(","));
  params.set("limit", String(limit));
  return expectJsonOrDetail(fetch(`${API_BASE}/deals?${params}`));
}
```

(Add the `DealsResponse` / `DealAssessment` / `DealPricePoint` / `DealThresholds` imports at the top of `client.ts`.)

- [ ] **Step 2: Write the failing Deals test**

Create `frontend/src/__tests__/Deals.test.tsx`. Match the existing test setup (jsdom, MSW or fetch mock — read `AlertsFeed.test.tsx` to see which the project uses). Cover: ranked deals render; `listings_unavailable` → "Set a listings source key"; `listings_empty` → "No active listings"; no-raw-market → rip edge `—` + "no market price"; no-graded-comps → flip edges `—`; deal chips appear only when `is_rip`/`is_flip`; the "investigate before buying" caveat is present; the watchlist toggle calls `getDealsFeed` with watched card ids.

```tsx
// Sketch — match the project's fetch-mock idiom from AlertsFeed.test.tsx.
import { render, screen, waitFor } from "@testing-library/react";
import Deals from "../components/Deals";

const deal = {
  listing_id: "L1", title: "Charizard ex 215", listing_price: 80.0, currency: "USD",
  url: "https://ebay.com/1", condition: "Raw", listing_type: "fixed_price",
  auction_end_at: null, fetched_at: "2026-08-02T00:00:00Z",
  raw_market: { price: 120.0, source: "tcgplayer", source_updated_at: "2026-08-01" },
  rip_edge: 40.0, psa9_comp: null,
  psa10_comp: { price: 200.0, source: "pkmnprices", source_updated_at: "2026-08-01" },
  flip_edge_to_9: null, flip_edge_to_10: 95.0, grading_fee: 25.0,
  deal_score: 95.0, is_rip: true, is_flip: true,
};

test("renders a ranked deal with rip + flip chips and the investigate caveat", async () => {
  // mock getDealsFeed → { deals: [deal], listings_unavailable: false, listings_empty: false, thresholds: {...} }
  render(<Deals />);
  await waitFor(() => expect(screen.getByText(/Charizard ex 215/)).toBeInTheDocument());
  expect(screen.getByText(/RIP/i)).toBeInTheDocument();
  expect(screen.getByText(/FLIP/i)).toBeInTheDocument();
  expect(screen.getByText(/investigate before buying/i)).toBeInTheDocument();
});

test("listings_unavailable shows the set-a-key empty state", async () => {
  // mock → { listings_unavailable: true, deals: [], ... }
  render(<Deals />);
  await waitFor(() => expect(screen.getByText(/Set a listings source key/i)).toBeInTheDocument());
});

test("no raw market shows em dash rip edge and no market price", async () => {
  // mock → deal with raw_market: null, rip_edge: null
  render(<Deals />);
  await waitFor(() => expect(screen.getByText(/no market price/i)).toBeInTheDocument());
});
```

- [ ] **Step 3: Implement `Deals.tsx`**

Create `frontend/src/components/Deals.tsx`: a header (search box debounced 300ms → `searchCards`, and a "Watched cards" toggle defaulting on), the deal feed (ranked `DealAssessment` cards), and honest empty states. Each deal card shows: card title, listing price (`formatMoney`), source badge, condition, auction timer (relative, reuse the 3c relative-time helper), the Rip row (raw market price + source/staleness + rip edge or `—` + "below market"/"no market price"), the Flip row (PSA-10 comp + flip-to-10 + flip-to-9 + "after $<fee> fee" or `—`), deal chips (🟢 RIP / 🟡 FLIP / none), and the footer caveat "Investigate before buying — keyword listings carry seller-mislabel noise." Tap → opens `url` (external). Honest-empty branches per the test. Reuse `formatMoney` and the relative-time util from 3c.

- [ ] **Step 4: Add the Deals tab to AppShell**

In `frontend/src/components/AppShell.tsx`, add a 6th nav entry "Deals" between Alerts and Browse (Scan · Vault · Alerts · Deals · Browse · More). Adjust the bottom-nav CSS so 6 compact tabs fit (reduce per-tab min-width / font-size — match the existing nav style; the 3c nav was built for 5, so a small CSS tweak is expected). Default the Deals tab to fetch the watched-cards feed on mount.

- [ ] **Step 5: Add deal-score chips to CardDetail**

In `frontend/src/components/CardDetail.tsx`, alongside the existing listings fetch (3c), also `getDeals(cardId, variant)` and render a compact chip on each listing row: `🟢 RIP $X` if `is_rip`, `🟡 FLIP $X` if `is_flip`, else a muted "not a deal". Keep the existing listings honest-empty states intact. Add a test in `frontend/src/__tests__/CardDetail.test.tsx` that a deal chip renders when a listing is a rip.

- [ ] **Step 6: Run frontend tests + build**

Run: `cd C:\ClaudeKnowledge && npm --prefix frontend test -- --run`
Expected: PASS (90 + new tests).

Run: `cd C:\ClaudeKnowledge && npm --prefix frontend run build`
Expected: clean build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Deals.tsx frontend/src/components/AppShell.tsx \
        frontend/src/components/CardDetail.tsx frontend/src/api/client.ts \
        frontend/src/api/types.ts frontend/src/__tests__/Deals.test.tsx \
        frontend/src/__tests__/CardDetail.test.tsx
git commit -m "feat(deals): Deals tab + CardDetail deal chips (T4)

6th bottom-nav Deals tab with a ranked deal feed (search a card or pull
watched cards), per-deal rip/flip edges, deal chips, staleness, and the
'investigate before buying' caveat. CardDetail gains per-listing
deal-score chips. Honest empty states throughout — set-a-key, no active
listings, no market price, no graded comps. formatMoney's no-comma
convention preserved."
```

---

## Task 5: Site — Deals section + roadmap update

**Files:**
- Create: `site/app/sections/Deals.tsx`
- Modify: `site/app/sections/data.ts` (Phase 05 subtitle)
- Modify: `site/app/page.tsx` (render `<Deals/>` after `<Alerts/>`)

**Pattern note:** Read `site/app/sections/Alerts.tsx` and `Grading.tsx` first — they set the scroll-animated section pattern (GSAP `gsap.context` + `ScrollTrigger` scrub staggered reveal, `is-lit` class, Framer reveal, `prefers-reduced-motion` static fallback, CSS defaults visible JS-off). Match them line-for-line in structure.

- [ ] **Step 1: Update the roadmap data**

In `site/app/sections/data.ts`, change the Phase 05 row to `status: "progress"` with subtitle `"Deal sniper (rip-vs-flip) shipped — sealed EV still planned"` (matching the Alerts row's progress phrasing). `SHIPPED_COUNT` recomputes from `done` rows automatically — leave it.

- [ ] **Step 2: Implement `site/app/sections/Deals.tsx`**

Create `site/app/sections/Deals.tsx` mirroring `Alerts.tsx`: a scroll-scrubbed rip-vs-flip diagram — a raw listing node splits into two paths, **Rip** (→ raw sold-comp market, "buy below market") and **Flip** (→ grading → PSA-10 slab comp, "buy raw, grade, sell"). Bars fill on scroll. Five deal-chip-style labels. Honest caption: *"Deal edges are indicative leads from marketplace keyword search, not guaranteed arbitrage — always verify the listing."* `prefers-reduced-motion` → static; CSS visible JS-off. Export the same default `<Deals/>` signature the other sections use.

- [ ] **Step 3: Wire Deals into the page**

In `site/app/page.tsx`, render `<Deals/>` immediately after `<Alerts/>`.

- [ ] **Step 4: Build the site + redeploy to docs**

Run: `cd C:\ClaudeKnowledge && npm --prefix site run build`
Expected: clean static export to `site/out/`.

Copy `site/out/` into `docs/` (preserve `docs/.nojekyll` + `docs/superpowers/` — do NOT `rm -rf docs/`; remove only the prior Next.js output, then copy the new `out/`). Match the T8 deploy step from the 3c plan.

Verify: `docs/index.html` contains `id="deals"` (or the Deals section markup); `docs/superpowers/plans/2026-08-03-deal-sniper.md` + the spec are intact; `docs/.nojekyll` present (0 bytes).

- [ ] **Step 5: Commit**

```bash
git add site/app/sections/Deals.tsx site/app/sections/data.ts site/app/page.tsx docs/
git commit -m "feat(deals): scroll-animated Deals site section + roadmap 05 progress (T5)

Rip-vs-flip diagram with the honest 'indicative leads, not guaranteed
arbitrage' caption. Roadmap 05 -> in-progress ('deal sniper shipped —
sealed EV still planned'). Rebuilt docs/ (nojekyll + superpowers/ preserved)."
```

---

## Task 6: Integrate, verify, docs, push, deploy

**Files:**
- Modify: `AI_CONTEXT.md` (new §12 deals; state table 05 progress; test counts; layout `deals/`; CLI `find-deals`)
- Modify: `PROJECT.md` (roadmap row 3c→05; shipped section; next-step)

- [ ] **Step 1: Run the full verification suite end-to-end**

```bash
cd C:\ClaudeKnowledge
backend/.venv/Scripts/python -m pytest -q                                  # backend: 443 -> N, all green
backend/.venv/Scripts/python -c "from cardplatform.db.session import Database; import sqlalchemy; s=Database().session().__enter__(); print(s.execute(sqlalchemy.text('SELECT count(*) FROM scan_logs')).scalar()); s.close()"  # scan_logs == 105
npm --prefix frontend test -- --run                                       # frontend: 90 -> N, all green
npm --prefix frontend run build                                           # clean
npm --prefix site run build                                               # clean
```

Expected: all green; scan_logs == 105 (sacred — data preserved).

- [ ] **Step 2: Manual smoke (backend :8000 + frontend :5173)**

- `GET /cards/base1-4/deals?variant=holofoil` (no key set) → `listings_unavailable: true`, `deals: []`.
- Open the Deals tab → honest "Set a listings source key" empty state.
- Open CardDetail for a card with listings → deal-score chips on listing rows.
- `cardplatform find-deals base1-4` → "No listings source key set …".
- (With a key set — if testable — deals flow; otherwise the honest-empty path is the verified path, same as graded prices in 3b.)

- [ ] **Step 3: Update AI_CONTEXT.md**

- State table: Phase 05 row `status: "progress"` (deal sniper shipped, sealed EV planned); add the §12 deals section.
- Test counts: 443 → new backend count; 90 → new frontend count.
- Layout: add the `deals/` package (`engine.py` DealEngine read-only, `api_models.py`) to the backend layout; add the `Deals.tsx` + CardDetail chip to the frontend layout; note the 6-tab nav.
- Run commands: add `cardplatform find-deals <card_id>`.
- Follow-ups: eBay Finding API works behind `CARDPLATFORM_LISTINGS_API_KEY` (App ID); deal alerts + deal snapshots + sealed EV deferred.

- [ ] **Step 4: Update PROJECT.md**

- Roadmap: Phase 05 → "In progress — deal sniper (rip-vs-flip) shipped; sealed EV planned".
- Add a "Phase 05 (deal sniper) — shipped" section mirroring the 3c one: the deal model, the read-only engine, the Finding-API adapter realness leg (unblocks 3c alerts), the 6-tab UI, the site section, honest-empty contract, documented follow-ups (sealed EV, deal alerts, deal snapshots).
- Next step: sealed-product EV (needs a sealed-product price provider) OR the full grade predictor (still blocked on labelled-data accrual).

- [ ] **Step 5: Commit docs**

```bash
git add AI_CONTEXT.md PROJECT.md
git commit -m "docs: record Phase 05 deal sniper (rip-vs-flip)

AI_CONTEXT §12 + state table (05 in-progress), layout (deals/ + 6-tab nav),
test counts, find-deals CLI. PROJECT roadmap + shipped section. Sealed EV,
deal alerts, deal snapshots noted as follow-ups."
```

- [ ] **Step 6: Push to origin/main (triggers Pages redeploy)**

```bash
cd C:\ClaudeKnowledge && git push origin main
```

- [ ] **Step 7: Confirm GitHub Pages deploy**

```bash
sleep 20 && gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds --jq '.[0] | {status, conclusion, commit}'
# wait until status == "built" (not "errored"); force a rebuild if stuck:
# gh api -X POST repos/Lucas-Bianco/pokemon-card-platform/pages/builds
```

Verify the live site shows the new Deals section + roadmap "05 … In progress":
```bash
# WebFetch https://lucas-bianco.github.io/pokemon-card-platform/ and confirm
# the Deals section + "05" in-progress subtitle render.
```

---

## Verification (end-to-end summary)

- **Backend:** pytest all green (443 + ~25 new); scan_logs == 105 (data preserved); `find-deals base1-4` honest "no key" message; `GET /cards/{id}/deals` honest flags + ranked deals.
- **Frontend:** vitest green (90 + new); `npm run build` clean; Deals tab + CardDetail chips render honest empty states.
- **Site:** `npm run build` → `out/` → `docs/`; `docs/index.html` shows Deals section; `docs/superpowers/` + `.nojekyll` intact; push → live Pages redeploy confirmed.
- **Sacred constraints:** only `latest_price` / `latest_graded` / `latest_listings`; read-only engine (no snapshot writes); staleness surfaced; honest empty states; no `data/` deletions; `func.lower(...).like`; Python 3.12 via `backend/.venv`.

## Out of scope (deferred)

- Sealed-product EV (needs a sealed-product price provider — Phase 05's other leg).
- Deal alerts (compose the 3c alert engine with this evaluator — a clean follow-up).
- Persisting deal scores / deal history (a `deal_snapshots` table — deals are on-demand now).
- Multi-source listings (only eBay; the Protocol keeps a second source swappable).
- Full-catalog deal scan (the feed scopes to watched + searched cards; a bulk scan is deferred).
- eBay OAuth / Browse API (Finding API's one-key auth is simpler; Browse is an upgrade path).