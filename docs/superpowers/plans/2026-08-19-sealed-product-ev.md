# Sealed-Product Deal Sniper (flip-edge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a query-keyed, eBay-backed sealed-product flip-edge deal sniper (Phase 05c) —
the unblocked half of Phase 05's sealed-EV leg — with honest empty states and no new schema.

**Architecture:** New `sealed/` package: a `SealedListingsProvider` Protocol + eBay adapter
methods (`fetch_listings_by_query` / `fetch_sold_listings_by_query`) reusing the existing
Finding-API `_search`/`_search_completed`, a read-only `SealedDealEngine` (median sold comp
→ flip_edge → ranked, honest nulls), a `GET /sealed/deals` route + CLI, and a 7th "Sealed"
frontend tab. On-demand, no writes, no new table. Rip EV (pull-rate-based) deferred.

**Tech Stack:** Python 3.12 (backend `.venv`), FastAPI, httpx+tenacity, Pydantic v2,
pytest; React 19 + TypeScript + Vite, vitest; Next.js 15 static export (site).

**Verify gates (run from repo root `C:\ClaudeKnowledge`):**
- Backend tests: `backend\.venv\Scripts\python.exe -m pytest` (must stay green; grows from 505).
- Frontend tests: `npm --prefix frontend test -- --run` (must stay green; grows from 106).
- Frontend build: `npm --prefix frontend run build`.
- Site build: `npm --prefix site run build`.
- 105-scan baseline (recognition untouched, but run to prove 0 regressions):
  `backend\.venv\Scripts\python.exe backend\scripts\evaluate_detection.py` (exit 0).
- **Python 3.12 only** via `backend\.venv`. Never delete anything under `data/`.

**Conventions (sacred):** never raise out of a fetch (degrade to `[]`); no ad-hoc price
resolution; honest empty states (no `$0`, no fabricated edge); immutable/on-demand (no
snapshot writes this phase); `func.lower().like` for any DB text search; match surrounding
style. Each task: TDD (failing test → impl → green → commit to `main`).

---

## File Structure

**Create (backend):**
- `backend/src/cardplatform/sealed/__init__.py` — empty package marker.
- `backend/src/cardplatform/sealed/provider.py` — `SealedListing`, `SealedSoldComp`,
  `SealedListingsProvider` Protocol.
- `backend/src/cardplatform/sealed/engine.py` — `SealedPricePoint`, `SealedThresholds`,
  `SealedDealAssessment`, `SealedDealResult`, `SealedDealEngine`.
- `backend/src/cardplatform/sealed/api_models.py` — Pydantic wire models.
- `backend/tests/test_sealed_provider.py`, `backend/tests/test_sealed_engine.py`,
  `backend/tests/test_sealed_deals_api.py`, `backend/tests/test_cli_sealed_deals.py`.

**Modify (backend):**
- `backend/src/cardplatform/prices/ebay_listings.py` — add query-keyed fetch + parse,
  DRY-extract shared per-item field extractors.
- `backend/src/cardplatform/config.py` — add 3 sealed settings.
- `backend/src/cardplatform/api.py` — add `GET /sealed/deals`.
- `backend/src/cardplatform/cli.py` — add `find-sealed-deals`.

**Create/modify (frontend):**
- `frontend/src/api/types.ts` — add sealed types.
- `frontend/src/api/client.ts` — add `getSealedDeals`.
- `frontend/src/components/SealedDeals.tsx` — new.
- `frontend/src/components/AppShell.tsx` — 7th tab.
- `frontend/src/__tests__/SealedDeals.test.tsx` — new; `client.test.ts` — add cases.

**Modify (site/docs):**
- `site/app/sections/data.ts` — roadmap row 05 sealed → in-progress.
- `AI_CONTEXT.md`, `PROJECT.md` — roadmap + phase writeup + next-step.

---

## Task 1: SealedListingsProvider Protocol + eBay query-keyed fetch

**Files:**
- Create: `backend/src/cardplatform/sealed/__init__.py`, `backend/src/cardplatform/sealed/provider.py`
- Modify: `backend/src/cardplatform/prices/ebay_listings.py` (additive + DRY refactor)
- Test: `backend/tests/test_sealed_provider.py`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_sealed_provider.py`

```python
"""Tests for the sealed-product listings provider (query-keyed, eBay)."""
from __future__ import annotations

import cardplatform.prices.ebay_listings as el
from cardplatform.config import Settings
from cardplatform.prices.ebay_listings import EbayListingsProvider
from cardplatform.sealed.provider import SealedListing, SealedSoldComp, SealedListingsProvider


def _find_items_payload(items):
    return {"findItemsByKeywordsResponse": [{"searchResult": [{"item": items}]}]}


def _completed_items_payload(items):
    return {"findCompletedItemsResponse": [{"searchResult": [{"item": items}]}]}


def _item(item_id, price, title="Sealed Box", listing_type="FixedPrice", state=None, cond=None):
    item = {
        "itemId": [str(item_id)],
        "title": [title],
        "sellingStatus": [{"currentPrice": [{"__value__": str(price), "@currencyId": "USD"}]}],
        "listingInfo": [{"listingType": [listing_type]}],
        "viewItemURL": ["https://ebay.example/it/" + str(item_id)],
    }
    if state is not None:
        item["sellingStatus"][0]["sellingState"] = [state]
    if cond is not None:
        item["condition"] = [{"conditionDisplayName": [cond]}]
    return item


def test_no_key_returns_empty_listings_without_network(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key=None))
    called = {"n": 0}
    monkeypatch.setattr(el.httpx, "get", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or (_ for _ in ()).throw(AssertionError("no network")))
    assert provider.fetch_listings_by_query("scarlet violet booster box") == []
    assert called["n"] == 0  # never touched the network


def test_fetch_listings_by_query_parses_items_into_sealed_listings(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key="app-id"))
    payload = _find_items_payload([_item(1, 120.0), _item(2, 135.0, listing_type="Auction")])
    monkeypatch.setattr(provider, "_search", lambda q: payload)
    listings = provider.fetch_listings_by_query("scarlet violet booster box")
    assert len(listings) == 2
    assert all(isinstance(l, SealedListing) for l in listings)
    assert listings[0].query == "scarlet violet booster box"
    assert listings[0].listing_id == "1"
    assert listings[0].price == 120.0
    assert listings[0].currency == "USD"
    assert listings[0].listing_type == "fixed_price"
    assert listings[0].source == "ebay"
    # No card_id on sealed listings (they are query-keyed, not card-keyed):
    assert not hasattr(listings[0], "card_id")
    assert listings[1].listing_type == "auction"
    assert listings[1].auction_end_at is None or hasattr(listings[1].auction_end_at, "tzinfo")


def test_fetch_listings_skips_items_missing_price_never_fabricates(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key="app-id"))
    bad = _item(3, 0.0)
    bad["sellingStatus"][0]["currentPrice"] = [{"__value__": ["not-a-number"], "@currencyId": "USD"}]
    payload = _find_items_payload([_item(1, 120.0), bad])
    monkeypatch.setattr(provider, "_search", lambda q: payload)
    listings = provider.fetch_listings_by_query("q")
    assert [l.listing_id for l in listings] == ["1"]  # bad one skipped, never $0


def test_fetch_listings_by_query_bad_json_returns_empty(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key="app-id"))
    monkeypatch.setattr(provider, "_search", lambda q: {"unexpected": "shape"})
    assert provider.fetch_listings_by_query("q") == []  # never raises


def test_fetch_sold_listings_by_query_gates_on_ended_with_sales(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key="app-id"))
    payload = _completed_items_payload([
        _item(10, 118.0, state="EndedWithSales"),
        _item(11, 200.0, state="EndedWithoutSales"),  # NOT a sale -> skipped
        _item(12, 121.0, state="EndedWithSales"),
    ])
    monkeypatch.setattr(provider, "_search_completed", lambda q, limit: payload)
    comps = provider.fetch_sold_listings_by_query("q", limit=10)
    assert len(comps) == 2
    assert all(isinstance(c, SealedSoldComp) for c in comps)
    assert [c.listing_id for c in comps] == ["10", "12"]
    assert comps[0].price == 118.0
    assert comps[0].source == "ebay"
    assert not hasattr(comps[0], "card_id")


def test_fetch_sold_listings_respects_limit(monkeypatch):
    provider = EbayListingsProvider(Settings(listings_api_key="app-id"))
    items = [_item(i, float(i), state="EndedWithSales") for i in range(1, 6)]
    monkeypatch.setattr(provider, "_search_completed", lambda q, limit: _completed_items_payload(items))
    assert len(provider.fetch_sold_listings_by_query("q", limit=3)) == 3


def test_ebay_provider_satisfies_sealed_listings_provider_protocol():
    # Structural typing: EbayListingsProvider has the *_by_query methods the Protocol requires.
    provider: SealedListingsProvider = EbayListingsProvider(Settings(listings_api_key=None))
    assert provider.name == "ebay"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_provider.py -q`
Expected: FAIL — `ImportError: No module named 'cardplatform.sealed'` (and `EbayListingsProvider` lacks `fetch_listings_by_query`).

- [ ] **Step 3: Create the `sealed` package + provider Protocol** — `backend/src/cardplatform/sealed/__init__.py`

```python
# empty
```

— `backend/src/cardplatform/sealed/provider.py`

```python
"""Sealed-product listings provider interface (Phase 05c).

Query-keyed sibling of `prices/listings_provider.py`. Sealed products (booster boxes, ETBs,
collection boxes, packs) are not cards — they have no `card_id`/`variant`, so they carry the
free-text `query` the user searched for. A provider that cannot reach its source, has no
API key configured, or receives an unparseable response returns [] — it NEVER raises (the
same discipline as ListingsProvider / GradedPriceProvider). Callers treat [] as "no
listings/sold comps for this query", not an error.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SealedListing:
    """One active marketplace listing for a sealed-product query.

    Mirrors `ListingQuote` but query-keyed (no card_id/variant). `price`/`currency` are the
    asking/bid price; fields the source omits are None, never fabricated. `listing_type` is
    "fixed_price" or "auction"; `auction_end_at` is the tz-aware UTC auction end or None.
    `source` is REQUIRED (no default). `source_updated_at` is None (Finding API exposes no
    per-listing stamp).
    """
    query: str
    listing_id: str
    source: str
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    listing_type: str | None = None
    auction_end_at: datetime | None = None
    url: str | None = None
    condition: str | None = None
    source_updated_at: str | None = None


@dataclass(frozen=True)
class SealedSoldComp:
    """One recently-sold eBay listing for a sealed-product query — sale evidence.

    Mirrors `SoldComp` but query-keyed. Distinct from SealedListing: a sold comp carries
    `sold_at` (sale close) and no listing_type/auction_end_at. NEVER persisted (on-demand
    evidence only); `source="ebay"`. Only confirmed sales (sellingState=="EndedWithSales").
    """
    query: str
    listing_id: str
    price: float
    title: str | None = None
    currency: str | None = None
    url: str | None = None
    condition: str | None = None
    sold_at: datetime | None = None
    source: str = "ebay"


class SealedListingsProvider(Protocol):
    """A source of active listings + sold comps for a sealed-product free-text query.

    Method names use the `_by_query` suffix so the concrete eBay adapter (which already has
    card-keyed `fetch_listings`/`fetch_sold_listings`) can implement both contracts without
    a name collision. A future TCGplayer sealed adapter implements the same methods.
    """
    name: str

    def fetch_listings_by_query(self, query: str) -> list[SealedListing]:
        """Active listings for the query. Returns [] on failure — never raises."""
        ...

    def fetch_sold_listings_by_query(self, query: str, limit: int = 3) -> list[SealedSoldComp]:
        """Up to `limit` recently-sold listings (sale evidence). [] on failure — never raises."""
        ...
```

- [ ] **Step 4: Add eBay query-keyed fetch + DRY refactor** — modify `backend/src/cardplatform/prices/ebay_listings.py`

Add the import of the sealed dataclasses near the existing `from cardplatform.prices.listings_provider import ...` (line 51):

```python
from cardplatform.sealed.provider import SealedListing, SealedSoldComp
```

Add these two public methods to `EbayListingsProvider` (after `fetch_sold_listings`, ~line 121):

```python
    def fetch_listings_by_query(self, query: str) -> list[SealedListing]:
        """Active eBay listings for a sealed-product free-text query (Phase 05c).

        Query-keyed sibling of `fetch_listings`: no card_id, no catalog lookup — the query
        IS the keyword. Same never-raise discipline: no key -> [] without a request; bad
        JSON / unexpected shape -> []; transport/5xx/429 retry then [].
        """
        if not self.settings.listings_api_key:
            return []
        payload = self._search(query)
        if payload is None:
            return []
        try:
            return self._parse_by_query(query, payload)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("ebay sealed listings parse failure for %r: %s", query, exc)
            return []

    def fetch_sold_listings_by_query(self, query: str, limit: int = 3) -> list[SealedSoldComp]:
        """Recently-sold eBay listings for a sealed-product query (Phase 05c, sale evidence).

        Query-keyed sibling of `fetch_sold_listings`. Same EndedWithSales gate (never
        fabricate a sale), same never-raise discipline, never persisted.
        """
        if not self.settings.listings_api_key:
            return []
        payload = self._search_completed(query, limit)
        if payload is None:
            return []
        try:
            return self._parse_completed_by_query(query, payload, limit)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("ebay sealed sold-comps parse failure for %r: %s", query, exc)
            return []
```

DRY-extract the shared per-item field extractors as `@staticmethod`s (add near the existing `_parse`, ~line 250). Then rewrite `_parse`/`_parse_completed` to delegate to them — **single-card behavior byte-for-byte unchanged.** Add the two `_extract_*` helpers:

```python
    @staticmethod
    def _extract_listing_fields(item: dict[str, Any]) -> dict[str, Any] | None:
        """Pull the common listing fields from one Finding-API item, or None if it should be
        skipped (missing itemId or unparseable/missing price — never fabricate). Shared by
        the card-keyed `_parse` and the query-keyed `_parse_by_query`.
        """
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        listing_id = _first(item, "itemId")
        if not listing_id:
            return None

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
                        return None  # price present but unparseable — skip, don't fake
        if price is None:
            return None  # missing price — skip, never fabricate (SACRED)

        listing_info = _first(item, "listingInfo")
        ltype_raw = _first(listing_info, "listingType") if isinstance(listing_info, dict) else None
        listing_type = "auction" if (isinstance(ltype_raw, str) and ltype_raw.startswith("Auction")) else "fixed_price"
        auction_end_at = (
            _parse_iso(_first(listing_info, "endTime"))
            if isinstance(listing_info, dict) and listing_type == "auction"
            else None
        )
        condition = None
        cond_block = _first(item, "condition")
        if isinstance(cond_block, dict):
            condition = _first(cond_block, "conditionDisplayName")
        return {
            "listing_id": str(listing_id),
            "title": _first(item, "title"),
            "price": price,
            "currency": currency,
            "listing_type": listing_type,
            "auction_end_at": auction_end_at,
            "url": _first(item, "viewItemURL"),
            "condition": condition,
        }

    @staticmethod
    def _extract_sold_fields(item: dict[str, Any]) -> dict[str, Any] | None:
        """Pull the common sold-comp fields from one completed item, or None if it should be
        skipped (not EndedWithSales, missing itemId, or missing price — never fabricate a
        sale). Shared by `_parse_completed` and `_parse_completed_by_query`.
        """
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        listing_id = _first(item, "itemId")
        if not listing_id:
            return None
        selling = _first(item, "sellingStatus")
        if not isinstance(selling, dict):
            return None
        if _first(selling, "sellingState") != "EndedWithSales":
            return None  # only confirmed sales — never fabricate
        price: float | None = None
        currency: str | None = None
        price_block = _first(selling, "currentPrice")
        if isinstance(price_block, dict):
            currency = price_block.get("@currencyId")
            raw_value = price_block.get("__value__")
            if raw_value is not None:
                try:
                    price = float(raw_value)
                except (TypeError, ValueError):
                    return None
        if price is None:
            return None
        listing_info = _first(item, "listingInfo")
        sold_at = _parse_iso(_first(listing_info, "endTime")) if isinstance(listing_info, dict) else None
        condition = None
        cond_block = _first(item, "condition")
        if isinstance(cond_block, dict):
            condition = _first(cond_block, "conditionDisplayName")
        return {
            "listing_id": str(listing_id),
            "price": price,
            "currency": currency,
            "title": _first(item, "title"),
            "url": _first(item, "viewItemURL"),
            "condition": condition,
            "sold_at": sold_at,
        }
```

Rewrite `_parse` to delegate (replaces the body at lines 251-329):

```python
    @staticmethod
    def _parse(card_id: str, variant: str, payload: dict[str, Any]) -> list[ListingQuote]:
        """Map eBay Finding API `findItemsByKeywordsResponse.searchResult.item`
        -> ListingQuotes. (Card-keyed; sealed queries use `_parse_by_query`.) Field
        extraction is shared via `_extract_listing_fields` — behavior unchanged.
        """
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        resp = payload.get("findItemsByKeywordsResponse")
        if not isinstance(resp, list) or not resp:
            return []
        search = _first(resp[0], "searchResult")
        if not isinstance(search, dict):
            return []
        items = search.get("item")
        if not isinstance(items, list):
            return []
        quotes: list[ListingQuote] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            f = EbayListingsProvider._extract_listing_fields(item)
            if f is None:
                continue
            quotes.append(ListingQuote(
                card_id=card_id, variant=variant, listing_id=f["listing_id"],
                title=f["title"], price=f["price"], currency=f["currency"],
                listing_type=f["listing_type"], auction_end_at=f["auction_end_at"],
                url=f["url"], condition=f["condition"], source="ebay", source_updated_at=None,
            ))
        return quotes
```

Rewrite `_parse_completed` to delegate (replaces the body at lines 332-407):

```python
    @staticmethod
    def _parse_completed(card_id: str, variant: str, payload: dict[str, Any], limit: int) -> list[SoldComp]:
        """Map findCompletedItemsResponse.searchResult.item -> SoldComps. (Card-keyed; sealed
        queries use `_parse_completed_by_query`.) Extraction shared via
        `_extract_sold_fields` (incl. the EndedWithSales gate) — behavior unchanged.
        """
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        resp = payload.get("findCompletedItemsResponse")
        if not isinstance(resp, list) or not resp:
            return []
        search = _first(resp[0], "searchResult")
        if not isinstance(search, dict):
            return []
        items = search.get("item")
        if not isinstance(items, list):
            return []
        comps: list[SoldComp] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            f = EbayListingsProvider._extract_sold_fields(item)
            if f is None:
                continue
            comps.append(SoldComp(
                card_id=card_id, variant=variant, listing_id=f["listing_id"],
                price=f["price"], currency=f["currency"], title=f["title"],
                url=f["url"], condition=f["condition"], sold_at=f["sold_at"], source="ebay",
            ))
            if len(comps) >= limit:
                break
        return comps
```

Add the two query-keyed parsers (after `_parse_completed`):

```python
    @staticmethod
    def _parse_by_query(query: str, payload: dict[str, Any]) -> list[SealedListing]:
        """Map findItemsByKeywordsResponse -> SealedListings (query-keyed). Same shape unwrap
        as `_parse`; field extraction shared via `_extract_listing_fields`."""
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        resp = payload.get("findItemsByKeywordsResponse")
        if not isinstance(resp, list) or not resp:
            return []
        search = _first(resp[0], "searchResult")
        if not isinstance(search, dict):
            return []
        items = search.get("item")
        if not isinstance(items, list):
            return []
        listings: list[SealedListing] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            f = EbayListingsProvider._extract_listing_fields(item)
            if f is None:
                continue
            listings.append(SealedListing(
                query=query, listing_id=f["listing_id"], source="ebay",
                title=f["title"], price=f["price"], currency=f["currency"],
                listing_type=f["listing_type"], auction_end_at=f["auction_end_at"],
                url=f["url"], condition=f["condition"], source_updated_at=None,
            ))
        return listings

    @staticmethod
    def _parse_completed_by_query(query: str, payload: dict[str, Any], limit: int) -> list[SealedSoldComp]:
        """Map findCompletedItemsResponse -> SealedSoldComps (query-keyed). EndedWithSales
        gate + extraction shared via `_extract_sold_fields` — never fabricates a sale."""
        def _first(node, key):
            v = node.get(key)
            return v[0] if isinstance(v, list) and v else None

        resp = payload.get("findCompletedItemsResponse")
        if not isinstance(resp, list) or not resp:
            return []
        search = _first(resp[0], "searchResult")
        if not isinstance(search, dict):
            return []
        items = search.get("item")
        if not isinstance(items, list):
            return []
        comps: list[SealedSoldComp] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            f = EbayListingsProvider._extract_sold_fields(item)
            if f is None:
                continue
            comps.append(SealedSoldComp(
                query=query, listing_id=f["listing_id"], price=f["price"],
                currency=f["currency"], title=f["title"], url=f["url"],
                condition=f["condition"], sold_at=f["sold_at"], source="ebay",
            ))
            if len(comps) >= limit:
                break
        return comps
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_provider.py backend/tests/test_listings_provider.py backend/tests/test_ebay_sold_comps.py -q`
Expected: PASS (new sealed tests green; existing listings/sold-comps tests still green — refactor is behavior-preserving).

- [ ] **Step 6: Commit**

```bash
cd C:\ClaudeKnowledge
git add backend/src/cardplatform/sealed/__init__.py backend/src/cardplatform/sealed/provider.py backend/src/cardplatform/prices/ebay_listings.py backend/tests/test_sealed_provider.py
git commit -m "feat(sealed): SealedListingsProvider Protocol + eBay query-keyed fetch (T1)"
```

---

## Task 2: SealedDealEngine (read-only flip-edge)

**Files:**
- Create: `backend/src/cardplatform/sealed/engine.py`
- Test: `backend/tests/test_sealed_engine.py`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_sealed_engine.py`

```python
"""Tests for SealedDealEngine — read-only flip-edge for sealed products (Phase 05c)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from cardplatform.config import Settings
from cardplatform.sealed.engine import SealedDealEngine, SealedDealAssessment
from cardplatform.sealed.provider import SealedListing, SealedSoldComp


@dataclass
class FakeProvider:
    name: str = "fake"
    def __init__(self, listings=(), comps=()):
        self._listings = list(listings)
        self._comps = list(comps)
    def fetch_listings_by_query(self, query):
        return list(self._listings)
    def fetch_sold_listings_by_query(self, query, limit=3):
        return list(self._comps)


def _listing(id_, price, listing_type="fixed_price"):
    return SealedListing(query="q", listing_id=str(id_), source="ebay",
                         title=f"L{id_}", price=price, currency="USD",
                         listing_type=listing_type, url=f"u{id_}")


def _comp(id_, price):
    return SealedSoldComp(query="q", listing_id=str(id_), price=price, currency="USD",
                           title=f"C{id_}", url=f"cu{id_}", sold_at=None, source="ebay")


def _engine(listings=(), comps=(), **overrides):
    settings = Settings(sealed_flip_min_abs=20.0, sealed_flip_min_pct=0.05,
                        sealed_sold_comp_limit=10, **overrides)
    return SealedDealEngine(FakeProvider(listings, comps), settings=settings)


def test_sealed_market_is_median_of_sold_comps():
    e = _engine(comps=[_comp(1, 100.0), _comp(2, 120.0), _comp(3, 200.0)])  # median 120
    r = e.assess("q", limit=20)
    assert r.sealed_market is not None and r.sealed_market.price == 120.0


def test_flip_edge_is_market_minus_listing_price():
    e = _engine(listings=[_listing(1, 90.0)], comps=[_comp(1, 120.0)])  # market 120
    r = e.assess("q", limit=20)
    a = r.assessments[0]
    assert a.flip_edge == 30.0
    assert a.is_flip is True  # 30 >= 20 abs and >= 0.05*120=6


def test_no_sold_comps_means_sealed_market_none_and_all_flip_edges_null():
    e = _engine(listings=[_listing(1, 90.0)], comps=[])
    r = e.assess("q", limit=20)
    assert r.sealed_market is None
    assert r.assessments[0].flip_edge is None  # never a fabricated edge
    assert r.assessments[0].is_flip is False
    assert r.comps_count == 0


def test_listing_missing_price_has_null_flip_edge_never_zero():
    e = _engine(listings=[SealedListing(query="q", listing_id="1", source="ebay",
                                         title="L1", price=None, currency="USD")],
                comps=[_comp(1, 120.0)])
    r = e.assess("("q", limit=20) if False else "q", limit=20)  # placeholder removed below
```

> NOTE: fix the last test's stray line — the intended assertion engine call is `e.assess("q", limit=20)`. Replace the malformed line with:

```python
def test_listing_missing_price_has_null_flip_edge_never_zero():
    e = _engine(listings=[SealedListing(query="q", listing_id="1", source="ebay",
                                         title="L1", price=None, currency="USD")],
                comps=[_comp(1, 120.0)])
    r = e.assess("q", limit=20)
    a = r.assessments[0]
    assert a.flip_edge is None  # missing listing price -> null edge, never $0
    assert a.is_flip is False


def test_deals_ranked_by_flip_edge_desc_nulls_last():
    e = _engine(listings=[_listing(1, 100.0), _listing(2, 80.0), _listing(3, 130.0)],
                comps=[_comp(1, 120.0)])  # market 120 -> edges 20, 40, -10
    r = e.assess("q", limit=20)
    scores = [a.flip_edge for a in r.assessments]
    assert scores == [40.0, 20.0, -10.0]  # desc


def test_is_flip_respects_both_abs_and_pct_thresholds():
    # flip_edge = 25, market = 120 -> pct threshold = 6; 25>=6 and 25>=20 -> flip
    e = _engine(listings=[_listing(1, 95.0)], comps=[_comp(1, 120.0)])
    assert _engine_assess_is_flip(e) is True
    # Raise abs threshold above the edge -> not a flip despite pct passing
    e2 = _engine(listings=[_listing(1, 95.0)], comps=[_comp(1, 120.0)], sealed_flip_min_abs=30.0)
    assert _engine_assess_is_flip(e2) is False


def _engine_assess_is_flip(engine):
    return engine.assess("q", limit=20).assessments[0].is_flip


def test_empty_query_listings_returns_empty_assessments_never_raises():
    e = _engine(listings=[], comps=[_comp(1, 120.0)])
    r = e.assess("q", limit=20)
    assert r.assessments == []
    assert r.listings_count == 0


def test_deal_score_is_flip_edge_or_null():
    e = _engine(listings=[_listing(1, 90.0)], comps=[_comp(1, 120.0)])
    a = e.assess("q", limit=20).assessments[0]
    assert a.deal_score == 30.0
    e2 = _engine(listings=[_listing(1, 90.0)], comps=[])
    a2 = e2.assess("q", limit=20).assessments[0]
    assert a2.deal_score is None  # nulls last
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_engine.py -q`
Expected: FAIL — `ImportError: cannot import name 'SealedDealEngine'`.

- [ ] **Step 3: Implement the engine** — `backend/src/cardplatform/sealed/engine.py`

```python
"""SealedDealEngine — flip-edge evaluation of sealed-product listings (Phase 05c).

READ-ONLY. Computes per-listing flip-edges on demand from a SealedListingsProvider's
active listings + sold comps. Writes nothing — deals are derived fresh each call, so they
never go stale in storage and the sacred-snapshot rule holds. Missing inputs null the edge
they feed — never a fabricated $0, never a fake profit.

sealed_market = median(sold comp prices)            # None if no comps -> all flip_edges null
flip_edge     = sealed_market - listing.price        # None if market or listing.price missing
is_flip       = flip_edge is not None
                and flip_edge >= sealed_flip_min_abs
                and flip_edge >= sealed_flip_min_pct * sealed_market
deal_score    = flip_edge if not None else None      # ranking; nulls last

Edges are indicative leads — eBay keyword search carries seller-mislabel noise; the UI says
"investigate before buying". This engine never decides "buy" — it surfaces candidates. Rip EV
(opening for expected pull value) is deferred: it needs a product-contents master + pull-rate
tables we do not have (same blocked-on-data class as the full Grade predictor).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from cardplatform.config import Settings, settings as default_settings
from cardplatform.sealed.provider import SealedListing, SealedListingsProvider, SealedSoldComp


@dataclass(frozen=True)
class SealedPricePoint:
    """The market reference a listing was compared against (median of recent sold comps).

    `source` + `source_updated_at` travel with the figure so the UI can say where it came
    from — sold comps expose no per-sale source stamp, so `source_updated_at` is None.
    """
    price: float
    source: str
    source_updated_at: str | None


@dataclass(frozen=True)
class SealedThresholds:
    sealed_flip_min_abs: float
    sealed_flip_min_pct: float


@dataclass(frozen=True)
class SealedDealAssessment:
    query: str
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: object | None  # datetime | None
    fetched_at: object  # datetime
    sealed_market: SealedPricePoint | None
    flip_edge: float | None
    deal_score: float | None
    is_flip: bool
    thresholds: SealedThresholds


@dataclass(frozen=True)
class SealedDealResult:
    """The full on-demand assessment for one query: ranked assessments + the counts/flags
    the API needs to render honest empty states (unavailable is derived from settings at
    the API layer; empty is `count == 0` while a key is set)."""
    query: str
    assessments: list[SealedDealAssessment]
    listings_count: int
    comps_count: int
    sealed_market: SealedPricePoint | None
    thresholds: SealedThresholds


def _median(prices: list[float]) -> float | None:
    return statistics.median(prices) if prices else None


class SealedDealEngine:
    def __init__(
        self,
        provider: SealedListingsProvider,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or default_settings

    def assess(self, query: str, limit: int = 20) -> SealedDealResult:
        """Ranked flip-edge deals for one sealed-product query. Never raises — missing
        sold comps surface as a null `sealed_market` (and therefore null flip_edges)."""
        listings = self.provider.fetch_listings_by_query(query)[: max(0, limit)]
        comps = self.provider.fetch_sold_listings_by_query(query, self.settings.sealed_sold_comp_limit)

        comp_prices = [c.price for c in comps if c.price is not None]
        market_price = _median(comp_prices)
        sealed_market = (
            SealedPricePoint(price=market_price, source="ebay", source_updated_at=None)
            if market_price is not None else None
        )

        th = SealedThresholds(
            self.settings.sealed_flip_min_abs,
            self.settings.sealed_flip_min_pct,
        )
        now = datetime.now(timezone.utc)
        assessments: list[SealedDealAssessment] = []
        for row in listings:
            price = row.price
            flip_edge = (
                sealed_market.price - price
                if sealed_market is not None and price is not None
                else None
            )
            is_flip = (
                flip_edge is not None
                and sealed_market is not None
                and flip_edge >= th.sealed_flip_min_abs
                and flip_edge >= th.sealed_flip_min_pct * sealed_market.price
            )
            assessments.append(SealedDealAssessment(
                query=query,
                listing_id=row.listing_id,
                title=row.title,
                listing_price=price,
                currency=row.currency,
                url=row.url,
                condition=row.condition,
                listing_type=row.listing_type,
                auction_end_at=row.auction_end_at,
                fetched_at=now,
                sealed_market=sealed_market,
                flip_edge=flip_edge,
                deal_score=flip_edge,  # sealed has a single edge; null when missing
                is_flip=is_flip,
                thresholds=th,
            ))

        # deal_score desc, nulls last.
        assessments.sort(key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0)))
        return SealedDealResult(
            query=query,
            assessments=assessments,
            listings_count=len(listings),
            comps_count=len(comps),
            sealed_market=sealed_market,
            thresholds=th,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/sealed/engine.py backend/tests/test_sealed_engine.py
git commit -m "feat(sealed): read-only SealedDealEngine flip-edge (T2)"
```

---

## Task 3: Settings + wire models + API route + CLI

**Files:**
- Create: `backend/src/cardplatform/sealed/api_models.py`
- Modify: `backend/src/cardplatform/config.py`, `backend/src/cardplatform/api.py`, `backend/src/cardplatform/cli.py`
- Test: `backend/tests/test_sealed_deals_api.py`, `backend/tests/test_cli_sealed_deals.py`

- [ ] **Step 1: Add settings** — modify `backend/src/cardplatform/config.py`

Add three fields to `Settings` (in the deals-settings block, after `deal_flip_min_abs` ~line 115). Keep them nullable-safe with defaults; add a validator clamp for `sealed_sold_comp_limit`. Use the same `field_validator` import style already present for `batch_ocr_workers`:

```python
    # Phase 05c — sealed-product flip-edge (reuses CARDPLATFORM_LISTINGS_API_KEY;
    # sealed products ARE eBay listings, so no separate sealed key is needed).
    sealed_flip_min_abs: float = 20.0
    sealed_flip_min_pct: float = 0.05
    sealed_sold_comp_limit: int = 10  # how many sold comps drive the market median
```

Add a validator (mirror the existing `batch_ocr_workers` clamp pattern):

```python
    @field_validator("sealed_sold_comp_limit")
    @classmethod
    def _clamp_sealed_sold_comp_limit(cls, v: int) -> int:
        return max(1, min(v, 100))
```

(If `field_validator` is not yet imported, add it to the existing pydantic import line.)

- [ ] **Step 2: Write the wire models** — `backend/src/cardplatform/sealed/api_models.py`

```python
"""Pydantic wire models for the Phase 05c sealed-deals API.

Mirrors `deals/api_models.py`: Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`
so the engine's dataclasses serialise directly. Every nullable field surfaces as None — a
missing edge input (no sold comps) is never a fabricated $0.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SealedPricePointOut(BaseModel):
    """The market reference (median of recent sold comps) compared against each listing.

    `source` + `source_updated_at` travel with the figure; sold comps expose no per-sale
    stamp so `source_updated_at` is None.
    """
    price: float
    source: str
    source_updated_at: str | None


class SealedThresholdsOut(BaseModel):
    sealed_flip_min_abs: float
    sealed_flip_min_pct: float


class SealedDealAssessmentOut(BaseModel):
    """One ranked sealed listing with its flip-edge + flag.

    `flip_edge` / `deal_score` are null when `sealed_market` is None (no sold comps) or the
    listing price is missing — never a fabricated $0. `sealed_market` is null when no sold
    comps exist. `is_flip` is an honest boolean against the thresholds; a null edge is never
    a deal.
    """
    model_config = ConfigDict(from_attributes=True)

    query: str
    listing_id: str
    title: str | None
    listing_price: float | None
    currency: str | None
    url: str | None
    condition: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    fetched_at: datetime
    sealed_market: SealedPricePointOut | None
    flip_edge: float | None
    deal_score: float | None
    is_flip: bool


class SealedDealsResponse(BaseModel):
    """Sealed-product deal feed for one query.

    `listings_unavailable` is True when no `listings_api_key` is configured (sealed reuses
    the eBay listings key — no separate sealed key). `listings_empty` is True when a key IS
    set but no active listings were found. `comps_unavailable` / `comps_empty` mirror that
    for the sold comps that establish `sealed_market`. `sealed_market` is null when no
    sold comps -> every `flip_edge` is null (honest, never $0).
    """
    query: str
    limit: int
    listings_unavailable: bool
    listings_empty: bool
    comps_unavailable: bool
    comps_empty: bool
    sealed_market: SealedPricePointOut | None
    deals: list[SealedDealAssessmentOut]
    thresholds: SealedThresholdsOut
```

- [ ] **Step 3: Write the failing API + CLI tests** — `backend/tests/test_sealed_deals_api.py`

```python
"""Tests for GET /sealed/deals (Phase 05c)."""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from cardplatform.api import create_app
from cardplatform.sealed.engine import SealedDealResult, SealedDealAssessment, SealedPricePoint, SealedThresholds
from cardplatform.sealed.provider import SealedListing, SealedSoldComp


def _stub_result(query="scarlet violet booster box", listings=1, comps=3, market=120.0):
    assessments = [
        SealedDealAssessment(
            query=query, listing_id=f"L{i}", title=f"L{i}", listing_price=100.0,
            currency="USD", url=f"u{i}", condition="New", listing_type="fixed_price",
            auction_end_at=None, fetched_at=datetime(2026, 8, 19),
            sealed_market=SealedPricePoint(market, "ebay", None) if market is not None else None,
            flip_edge=(market - 100.0) if market is not None else None,
            deal_score=(market - 100.0) if market is not None else None,
            is_flip=False, thresholds=SealedThresholds(20.0, 0.05),
        ) for i in range(listings)
    ]
    return SealedDealResult(query=query, assessments=assessments, listings_count=listings,
                            comps_count=comps,
                            sealed_market=SealedPricePoint(market, "ebay", None) if market is not None else None,
                            thresholds=SealedThresholds(20.0, 0.05))


def _client(monkeypatch, result=None, key="app-id"):
    app = create_app()
    monkeypatch.setattr("cardplatform.api.settings", type("S", (), {
        "listings_api_key": key, "sealed_flip_min_abs": 20.0, "sealed_flip_min_pct": 0.05,
        "sealed_sold_comp_limit": 10,
    })())
    # Replace the engine's assess with a stub so no network is hit.
    monkeypatch.setattr("cardplatform.sealed.engine.SealedDealEngine.assess",
                        lambda self, q, limit=20: result or _stub_result(q))
    return TestClient(app)


def test_sealed_deals_returns_ranked_deals(monkeypatch):
    client = _client(monkeypatch, _stub_result(listings=2, market=120.0))
    r = client.get("/sealed/deals", params={"q": "scarlet violet booster box", "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "scarlet violet booster box"
    assert body["listings_unavailable"] is False
    assert body["listings_empty"] is False
    assert body["comps_unavailable"] is False
    assert body["sealed_market"]["price"] == 120.0
    assert len(body["deals"]) == 2
    assert body["deals"][0]["flip_edge"] == 20.0


def test_sealed_deals_no_key_means_listings_and_comps_unavailable(monkeypatch):
    client = _client(monkeypatch, key=None)
    r = client.get("/sealed/deals", params={"q": "booster box"})
    assert r.status_code == 200
    body = r.json()
    assert body["listings_unavailable"] is True
    assert body["comps_unavailable"] is True
    assert body["deals"] == []  # engine still runs but provider returns []


def test_sealed_deals_empty_query_returns_422(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/sealed/deals", params={"q": "  "})
    assert r.status_code == 422  # whitespace-only query rejected


def test_sealed_deals_limit_clamped(monkeypatch):
    client = _client(monkeypatch, _stub_result())
    r = client.get("/sealed/deals", params={"q": "box", "limit": 999})
    assert r.status_code == 200
    assert r.json()["limit"] <= 50  # clamped to [1,50]


def test_sealed_deals_missing_query_returns_422(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/sealed/deals").status_code == 422


def test_sealed_deals_no_comps_means_sealed_market_null_and_flip_edges_null(monkeypatch):
    client = _client(monkeypatch, _stub_result(listings=1, comps=0, market=None))
    body = client.get("/sealed/deals", params={"q": "box"}).json()
    assert body["sealed_market"] is None
    assert body["deals"][0]["flip_edge"] is None  # never $0
```

— `backend/tests/test_cli_sealed_deals.py`

```python
"""Tests for `cardplatform find-sealed-deals` CLI (Phase 05c)."""
from __future__ import annotations

from cardplatform.cli import main


def test_find_sealed_deals_no_key_prints_honest_message(monkeypatch, capsys):
    monkeypatch.setattr("cardplatform.cli.settings", type("S", (), {
        "listings_api_key": None, "sealed_flip_min_abs": 20.0, "sealed_flip_min_pct": 0.05,
        "sealed_sold_comp_limit": 10,
    })())
    rc = main(["find-sealed-deals", "--query", "booster box"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no listings source key" in out.lower() or "set" in out.lower()


def test_find_sealed_deals_missing_query_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr("cardplatform.cli.settings", type("S", (), {"listings_api_key": "k"})())
    rc = main(["find-sealed-deals"])
    assert rc != 0  # --query required
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_deals_api.py backend/tests/test_cli_sealed_deals.py -q`
Expected: FAIL — no `/sealed/deals` route / no `find-sealed-deals` subcommand.

- [ ] **Step 5: Add the API route** — modify `backend/src/cardplatform/api.py`

Add imports near the existing deals imports:

```python
from cardplatform.prices.ebay_listings import EbayListingsProvider
from cardplatform.sealed.engine import SealedDealEngine
from cardplatform.sealed.api_models import (
    SealedDealAssessmentOut, SealedDealsResponse, SealedPricePointOut, SealedThresholdsOut,
)
```

Add the route (place it after the existing `GET /deals` block so the file stays grouped). Use a `Query` param for validation:

```python
@app.get("/sealed/deals", response_model=SealedDealsResponse)
def get_sealed_deals(
    q: str = Query(..., min_length=2, description="Sealed product search, e.g. 'scarlet violet booster box'"),
    limit: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
) -> SealedDealsResponse:
    """Ranked flip-edge deals for a sealed-product free-text query (Phase 05c).

    Sealed products (booster boxes, ETBs, collection boxes, packs) are queried on eBay via
    the same Finding API + App ID as listings — no separate key. Honest empty states: no
    key -> listings_unavailable/comps_unavailable; key set but no listings -> listings_empty;
    no sold comps -> sealed_market null -> every flip_edge null (never $0). Read-only: no
    snapshot writes. Rip EV (opening for expected pull value) is deferred — needs pull-rate
    data we don't have.
    """
    q = q.strip()
    if not q or len(q) < 2:
        raise HTTPException(status_code=422, detail="query must be at least 2 non-space chars")
    provider = EbayListingsProvider(settings)
    engine = SealedDealEngine(provider, settings=settings)
    result = engine.assess(q, limit=limit)
    key_set = bool(settings.listings_api_key)
    return SealedDealsResponse(
        query=q,
        limit=limit,
        listings_unavailable=not key_set,
        listings_empty=key_set and result.listings_count == 0,
        comps_unavailable=not key_set,
        comps_empty=key_set and result.comps_count == 0,
        sealed_market=SealedPricePointOut.model_validate(result.sealed_market)
            if result.sealed_market is not None else None,
        deals=[SealedDealAssessmentOut.model_validate(a) for a in result.assessments],
        thresholds=SealedThresholdsOut(
            sealed_flip_min_abs=settings.sealed_flip_min_abs,
            sealed_flip_min_pct=settings.sealed_flip_min_pct,
        ),
    )
```

> Note: `Query` and `HTTPException` are already imported in `api.py` (used by other routes). `get_session` is the existing dependency. If `Settings`-typed `settings` is not imported at module scope, use the existing `settings` singleton already referenced by other routes.

- [ ] **Step 6: Add the CLI subcommand** — modify `backend/src/cardplatform/cli.py`

Add a subparser in the existing `argparse` setup (mirror `find-deals`) and a handler:

```python
    # inside the subparser block, after find-deals:
    p_sealed = sub.add_parser("find-sealed-deals", help="Ranked flip-edge deals for a sealed product query (eBay).")
    p_sealed.add_argument("--query", required=True, help="Sealed product search, e.g. 'scarlet violet booster box'")
    p_sealed.add_argument("--limit", type=int, default=20)
```

Add the dispatch + handler (mirror the `find-deals` handler's honest-message style):

```python
    # in the command dispatch:
    elif cmd == "find-sealed-deals":
        rc = _cmd_find_sealed_deals(args)


def _cmd_find_sealed_deals(args) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.engine import SealedDealEngine

    if not settings.listings_api_key:
        print("no listings source key — set CARDPLATFORM_LISTINGS_API_KEY (eBay App ID) to query sealed deals")
        return 0
    db = Database()
    db.create_all()
    with db.session() as session:  # engine is read-only; session unused but kept for symmetry
        provider = EbayListingsProvider(settings)
        engine = SealedDealEngine(provider, settings=settings)
        result = engine.assess(args.query, limit=max(1, min(args.limit, 50)))
    if result.listings_count == 0:
        print(f"no active listings found for {args.query!r}")
        return 0
    if result.sealed_market is None:
        print(f"no recent sold comps to establish a market price for {args.query!r} — flip edges unavailable")
    print(f"sealed market (median sold): {result.sealed_market.price if result.sealed_market else '—'}")
    print(f"{'flip':>10}  {'price':>10}  listing_id  title")
    for a in result.assessments:
        edge = f"{a.flip_edge:.2f}" if a.flip_edge is not None else "—"
        price = f"{a.listing_price:.2f}" if a.listing_price is not None else "—"
        flag = "  💰FLIP" if a.is_flip else ""
        print(f"{edge:>10}  {price:>10}  {a.listing_id}  {a.title}{flag}")
    return 0
```

> Match the actual `Database`/`session` API used by the existing `find-deals` handler (read it before finalizing — keep the same pattern). If `find-deals` constructs no session (read-only), drop the `with db.session()` block and construct the engine directly.

- [ ] **Step 7: Run tests to verify they pass**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_sealed_deals_api.py backend/tests/test_cli_sealed_deals.py backend/tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full backend suite**

Run: `backend\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (505 + new tests, 0 regressions).

- [ ] **Step 9: Commit**

```bash
git add backend/src/cardplatform/sealed/api_models.py backend/src/cardplatform/config.py backend/src/cardplatform/api.py backend/src/cardplatform/cli.py backend/tests/test_sealed_deals_api.py backend/tests/test_cli_sealed_deals.py
git commit -m "feat(sealed): GET /sealed/deals + find-sealed-deals CLI + settings (T3)"
```

---

## Task 4: Frontend — Sealed tab + client + types + tests

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/SealedDeals.tsx`, `frontend/src/__tests__/SealedDeals.test.tsx`

- [ ] **Step 1: Add the types** — modify `frontend/src/api/types.ts` (append, mirroring `DealAssessment`/`DealsResponse`)

```typescript
// Phase 05c — sealed-product flip-edge (query-keyed, eBay). Mirrors backend
// SealedDealAssessmentOut / SealedDealsResponse field-for-field.

export interface SealedPricePoint {
  price: number;
  source: string;
  source_updated_at: string | null;
}

export interface SealedThresholds {
  sealed_flip_min_abs: number;
  sealed_flip_min_pct: number;
}

export interface SealedDealAssessment {
  query: string;
  listing_id: string;
  title: string | null;
  listing_price: number | null;
  currency: string | null;
  url: string | null;
  condition: string | null;
  listing_type: string | null;
  auction_end_at: string | null;
  fetched_at: string;
  sealed_market: SealedPricePoint | null;
  flip_edge: number | null;
  deal_score: number | null;
  is_flip: boolean;
}

export interface SealedDealsResponse {
  query: string;
  limit: number;
  listings_unavailable: boolean;
  listings_empty: boolean;
  comps_unavailable: boolean;
  comps_empty: boolean;
  sealed_market: SealedPricePoint | null;
  deals: SealedDealAssessment[];
  thresholds: SealedThresholds;
}
```

- [ ] **Step 2: Add the client function** — modify `frontend/src/api/client.ts` (append near the deals functions)

```typescript
import type { SealedDealsResponse } from "./types";

export async function getSealedDeals(query: string, limit = 20): Promise<SealedDealsResponse> {
  const u = new URL("/api/sealed/deals", window.location.origin);
  u.searchParams.set("q", query);
  u.searchParams.set("limit", String(limit));
  const res = await fetch(u.toString().replace(window.location.origin, ""));
  return expectJsonOrDetail<SealedDealsResponse>(res);
}
```

> Match the existing client's URL-building convention (other functions use string literals like `"/deals?..."`; read `getDeals` first and mirror its exact style — do not introduce a new pattern). If `expectJsonOrDetail` is the wrong helper for a 200 response, use `expectJson<SealedDealsResponse>`.

- [ ] **Step 3: Write the failing frontend tests** — `frontend/src/__tests__/SealedDeals.test.tsx`

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SealedDeals } from "../components/SealedDeals";

const okResponse = {
  query: "scarlet violet booster box",
  limit: 20,
  listings_unavailable: false,
  listings_empty: false,
  comps_unavailable: false,
  comps_empty: false,
  sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
  deals: [
    { query: "scarlet violet booster box", listing_id: "1", title: "SV Booster Box",
      listing_price: 95.0, currency: "USD", url: "https://ebay/1", condition: "New",
      listing_type: "fixed_price", auction_end_at: null, fetched_at: "2026-08-19T00:00:00Z",
      sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
      flip_edge: 25.0, deal_score: 25.0, is_flip: true },
  ],
  thresholds: { sealed_flip_min_abs: 20.0, sealed_flip_min_pct: 0.05 },
};

function mockFetch(body: unknown, status = 200) {
  global.fetch = vi.fn(async () => ({
    ok: status < 400, status,
    json: async () => body,
  }) as any);
}

beforeEach(() => { vi.clearAllMocks(); });

describe("SealedDeals", () => {
  it("renders the search box and a Find button", () => {
    mockFetch(okResponse);
    render(<SealedDeals />);
    expect(screen.getByPlaceholderText(/sealed product/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /find/i })).toBeInTheDocument();
  });

  it("fetches and shows ranked flip-edge deals", async () => {
    mockFetch(okResponse);
    render(<SealedDeals />);
    fireEvent.change(screen.getByPlaceholderText(/sealed product/i),
      { target: { value: "scarlet violet booster box" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));
    await waitFor(() => expect(screen.getByText(/SV Booster Box/)).toBeInTheDocument());
    expect(screen.getByText(/\$95\.00/)).toBeInTheDocument();       // listing price, never $0
    expect(screen.getByText(/flip/i)).toBeInTheDocument();
    expect(screen.getByText(/\$25\.00/)).toBeInTheDocument();        // flip edge
  });

  it("shows an honest 'set a key' empty state when listings_unavailable", async () => {
    mockFetch({ ...okResponse, deals: [], listings_unavailable: true, listings_empty: false,
                comps_unavailable: true, sealed_market: null });
    render(<SealedDeals />);
    fireEvent.change(screen.getByPlaceholderText(/sealed product/i), { target: { value: "box" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));
    await waitFor(() => expect(screen.getByText(/set.*CARDPLATFORM_LISTINGS_API_KEY|ebay app id/i)).toBeInTheDocument());
  });

  it("shows an honest 'no sold comps' state when sealed_market is null", async () => {
    mockFetch({ ...okResponse, deals: [
      { ...okResponse.deals[0], flip_edge: null, deal_score: null, is_flip: false }],
      comps_empty: true, sealed_market: null });
    render(<SealedDeals />);
    fireEvent.change(screen.getByPlaceholderText(/sealed product/i), { target: { value: "box" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));
    await waitFor(() => expect(screen.getByText(/no.*sold.*comp|market price/i)).toBeInTheDocument());
    // flip edge renders as em dash, never $0.00:
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it("never renders a fabricated $0.00 flip edge", async () => {
    mockFetch({ ...okResponse, deals: [
      { ...okResponse.deals[0], flip_edge: null, deal_score: null, is_flip: false }] });
    render(<SealedDeals />);
    fireEvent.change(screen.getByPlaceholderText(/sealed product/i), { target: { value: "box" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));
    await waitFor(() => expect(screen.getByText(/SV Booster Box/)).toBeInTheDocument());
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `npm --prefix frontend test -- --run SealedDeals`
Expected: FAIL — `Cannot find module '../components/SealedDeals'`.

- [ ] **Step 5: Implement the component** — `frontend/src/components/SealedDeals.tsx`

```typescript
import { useState } from "react";
import { getSealedDeals } from "../api/client";
import type { SealedDealsResponse, SealedDealAssessment } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

export function SealedDeals(): JSX.Element {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<SealedDealsResponse | null>(null);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (q.length < 2) { setError("Enter a sealed product to search (e.g. 'scarlet violet booster box')."); return; }
    setLoading(true); setError(null); setData(null);
    try {
      setData(await getSealedDeals(q));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch sealed deals.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="sealed-deals">
      <h2>Sealed product deals</h2>
      <p className="sealed-deals__help">
        Search a sealed product (booster box, ETB, collection box, pack) to find active eBay
        listings priced below the recent sold-comp median. Flip edges are indicative leads
        from keyword search — investigate before buying.
      </p>
      <form className="sealed-deals__form" onSubmit={run}>
        <input
          className="sealed-deals__input"
          type="search"
          placeholder="Sealed product, e.g. 'scarlet violet booster box'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Sealed product search"
        />
        <button type="submit" className="sealed-deals__btn" disabled={loading}>
          {loading ? "Searching…" : "Find deals"}
        </button>
      </form>

      {error && <p className="sealed-deals__error">{error}</p>}

      {data && <SealedDealsResult data={data} />}
    </div>
  );
}

function SealedDealsResult({ data }: { data: SealedDealsResponse }): JSX.Element {
  if (data.listings_unavailable) {
    return <EmptyState text="Set CARDPLATFORM_LISTINGS_API_KEY (your eBay App ID) to search sealed listings." />;
  }
  if (data.listings_empty) {
    return <EmptyState text={`No active listings found for “${data.query}”. Try a broader query.`} />;
  }
  return (
    <div className="sealed-deals__result">
      <div className="sealed-deals__market">
        Sealed market (median sold):{" "}
        {data.sealed_market ? formatMoney(data.sealed_market.price) : "—"}
        {data.sealed_market && <span className="sealed-deals__staleness"> {formatStaleness(data.sealed_market.source_updated_at)}</span>}
      </div>
      {data.sealed_market === null && (
        <p className="sealed-deals__note">No recent sold comps to establish a market price — flip edges unavailable.</p>
      )}
      <ul className="sealed-deals__list">
        {data.deals.map((d) => <SealedDealCard key={d.listing_id} d={d} />)}
      </ul>
      <p className="sealed-deals__caveat">Edges are gross of selling fees. Always verify the listing.</p>
    </div>
  );
}

function SealedDealCard({ d }: { d: SealedDealAssessment }): JSX.Element {
  return (
    <li className={`sealed-deal${d.is_flip ? " sealed-deal--flip" : ""}`}>
      <div className="sealed-deal__title">
        {d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.title ?? "Untitled"}</a> : (d.title ?? "Untitled")}
        {d.is_flip && <span className="sealed-deal__chip">💰 FLIP</span>}
      </div>
      <div className="sealed-deal__rows">
        <span>Price: {formatMoney(d.listing_price)}</span>
        <span>Flip edge: {d.flip_edge === null ? "—" : formatMoney(d.flip_edge)}</span>
        <span>{d.condition ?? "—"} · {d.listing_type ?? "—"}</span>
      </div>
    </li>
  );
}

function EmptyState({ text }: { text: string }): JSX.Element {
  return <p className="sealed-deals__empty">{text}</p>;
}
```

- [ ] **Step 6: Wire the 7th tab into AppShell** — modify `frontend/src/components/AppShell.tsx`

Extend the `TabView` union (add `"sealed"`), `TAB_TITLES` (add `sealed: "Sealed"`), add a `TabButton` in the bottom nav, and a branch in the view render that renders `<SealedDeals />`. Import `SealedDeals` at the top. Match the existing tab pattern exactly (read the `deals` branch and mirror it). Ensure the bottom nav still lays out on narrow phones (the project keeps ≤6 items visible; a 7th may require confirming the nav CSS — if the existing `.bottom-nav` is a flex row that wraps or scrolls, a 7th item is fine; if it hard-codes 6 equal columns, add `sealed` and let the grid count grow, then verify in the build).

- [ ] **Step 7: Run frontend tests to verify they pass**

Run: `npm --prefix frontend test -- --run`
Expected: PASS (106 + new tests, 0 regressions).

- [ ] **Step 8: Build the frontend**

Run: `npm --prefix frontend run build`
Expected: `tsc -b` + `vite build` succeed (no type errors — `JSX.Element` return types, strict mode).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/SealedDeals.tsx frontend/src/components/AppShell.tsx frontend/src/__tests__/SealedDeals.test.tsx frontend/src/__tests__/client.test.ts
git commit -m "feat(frontend): Sealed tab + sealed-deals client + types (T4)"
```

---

## Task 5: Site roadmap + docs (AI_CONTEXT, PROJECT) + ship

**Files:**
- Modify: `site/app/sections/data.ts`, `AI_CONTEXT.md`, `PROJECT.md`

- [ ] **Step 1: Update the site roadmap** — modify `site/app/sections/data.ts`

Find the Phase 05 roadmap row (currently "Deal sniper (rip-vs-flip) shipped — sealed EV still planned") and update it to reflect sealed flip-edge shipped, rip EV still planned. Match the existing row object's field names exactly. Example:

```typescript
{ id: "05", title: "Deal sniper + sealed EV", status: "in-progress",
  body: "Rip-vs-flip deal sniper + deal alerts + sold-comps shipped; sealed flip-edge shipped; rip EV (expected pull value) still planned — needs pull-rate data." },
```

- [ ] **Step 2: Rebuild the site → docs/**

Run:
```bash
npm --prefix site run build
# copy the static export into docs/, preserving .nojekyll and docs/superpowers/
```
Use the repo's existing deploy flow (read how prior phases did it — `site/out/` → `docs/`, keep `docs/.nojekyll` and `docs/superpowers/` intact). Do NOT delete `docs/superpowers/`.

- [ ] **Step 3: Update AI_CONTEXT.md**

- §2 roadmap table: Phase 5 row → "sealed flip-edge shipped; rip EV still planned"; test counts bumped (505 + new backend tests; 106 + new frontend tests).
- Add a new §15 "Phase 05c — sealed-product flip-edge" writeup mirroring the §12–§14 style (what shipped T1–T5, sacred constraints held, documented follow-ups: rip EV + product master + sealed snapshot table + TCGplayer sealed API).

- [ ] **Step 4: Update PROJECT.md**

- Roadmap table Phase 5 row → sealed flip-edge shipped; rip EV planned.
- "Next step" → mark sealed flip-edge done; next is either rip EV (blocked on pull-rate data) or the full Grade predictor (blocked on labelled data) or Phase 6 (set-completion optimizer).

- [ ] **Step 5: Full verification**

Run (from repo root):
```bash
backend\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
npm --prefix site run build
backend\.venv\Scripts\python.exe backend\scripts\evaluate_detection.py
```
Expected: backend green; frontend green; builds succeed; 105-scan baseline exit 0 (recognition untouched — 0 regressions).

- [ ] **Step 6: Commit + push**

```bash
git add site/app/sections/data.ts docs/ AI_CONTEXT.md PROJECT.md
git commit -m "docs: record Phase 05c sealed flip-edge + site roadmap (T5)"
git push origin main
```

> Per the standing directive: solo repo, push to `origin/main` directly (no PR). Confirm the
> GitHub Pages build via `gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds` and
> force a rebuild with `POST /repos/.../pages/builds` if needed.

---

## Self-Review (completed)

- **Spec coverage:** flip-edge math (T2) ✓, eBay query fetch (T1) ✓, API + CLI + settings (T3) ✓, frontend tab (T4) ✓, site/docs/ship (T5) ✓. Rip EV intentionally deferred (§2 of spec) — no task, by design.
- **Placeholders:** the one malformed test line in T2 Step 1 is explicitly corrected in the note that follows it (real code, not a placeholder). CLI handler notes to match the existing `find-deals` session pattern by reading it first — that's a real instruction, not a TODO.
- **Type consistency:** `SealedListing`/`SealedSoldComp` (T1) → consumed by `SealedDealEngine` (T2) → `SealedDealAssessment`/`SealedDealResult` (T2) → `SealedDealAssessmentOut`/`SealedDealsResponse` (T3) → `SealedDealAssessment`/`SealedDealsResponse` TS (T4) — names align across layers. `flip_edge`/`deal_score`/`is_flip`/`sealed_market` consistent end-to-end. `fetch_listings_by_query`/`fetch_sold_listings_by_query` consistent between Protocol (T1) and engine (T2) and adapter (T1).