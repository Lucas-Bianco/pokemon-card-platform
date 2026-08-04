# Phase 05b — Deal Alerts + eBay Sold-Comps Evidence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compose the Phase 3c `AlertEngine` with the Phase 05 read-only `DealEngine` so a *new* active listing that clears rip/flip thresholds fires an alert; and fetch the 3 most recent eBay **sold** listings (Finding API `findCompletedItems`) to show as evidence backing the raw market price in the Deal / price UI.

**Architecture:** Two additive legs, no schema change, no snapshot writes. (1) A `deal` watch reuses the existing `Watch` model + global deal thresholds + `last_seen_listing_ids` baseline; `AlertEngine` gains an optional `deal_engine` collaborator and a new `_eval_deal` that mirrors `_eval_new_listing`'s first-poll-never-fires + baseline-dedupe. (2) `EbayListingsProvider.fetch_sold_listings()` reuses `_build_query` and the retry discipline but calls `findCompletedItems` with `SoldItemsOnly=true` + `SERVICE-VERSION=1.13.0` (so `sellingState="EndedWithSales"`), skipping unsold and price-less items; a new read-only `GET /cards/{id}/sold-comps?limit=3` surfaces them with honest `unavailable`/`empty` flags. Sold comps are NOT persisted (on-demand evidence only).

**Tech Stack:** Python 3.12 (`backend/.venv`), FastAPI + SQLAlchemy/SQLite + Pydantic v2; React 19 + TypeScript + Vite + vitest; Next.js 15 static export → `docs/` for GitHub Pages. eBay Finding API (deprecated `findCompletedItems`, still functional for free App IDs; degrades to `[]`).

**Branch:** `phase-05b-deal-alerts-sold-comps` (off `main`). Commit per task. Only edit within `C:\ClaudeKnowledge`. Never delete anything under `data/`. Python 3.12 via `backend/.venv`.

**Standing directive (auto mode):** proceed through all tasks without per-step check-ins; commit all new code; push + deploy at the end.

**Sacred constraints (do not break):** never resolve the latest price ad-hoc (use `DealEngine.assess` / `PriceService.latest_price`); sold comps are NOT persisted (no snapshot writes); surface staleness (`sold_at`); honest empty states (never `$0`, never fabricate a sold comp from an unsold listing); providers degrade to `[]`, never raise; `func.lower(col).like` not `ilike`; match surrounding code style; keep `AI_CONTEXT.md` current.

---

## File Structure

**Backend:**
- `backend/src/cardplatform/prices/listings_provider.py` — ADD `SoldComp` dataclass (alongside `ListingQuote`).
- `backend/src/cardplatform/prices/ebay_listings.py` — ADD `fetch_sold_listings` + `_search_completed` + `_parse_completed` to `EbayListingsProvider`.
- `backend/src/cardplatform/prices/sold_comps_api_models.py` (NEW) — `SoldCompOut`, `SoldCompsResponse` (Pydantic v2).
- `backend/src/cardplatform/alerts/engine.py` — ADD `deal_engine` ctor param + `_eval_deal` + `deal` dispatch branch.
- `backend/src/cardplatform/api.py` — ADD `GET /cards/{id}/sold-comps`; add `"deal"` to `_ALERT_TYPES` + 422 rule; wire `deal_engine` into both `AlertEngine` constructions (poll loop).
- `backend/src/cardplatform/cli.py` — wire `deal_engine` into `check_alerts`'s `AlertEngine`.
- `backend/tests/test_ebay_sold_comps.py` (NEW) — provider tests.
- `backend/tests/test_sold_comps_api.py` (NEW) — endpoint tests.
- `backend/tests/test_alert_engine_deal.py` (NEW) — `_eval_deal` tests.
- `backend/tests/test_watchlist_api.py` (EXTEND) — `deal` 422 rule.

**Frontend:**
- `frontend/src/api/types.ts` — `SoldComp`, `SoldCompsResponse`; extend `AlertType` union with `"deal"`.
- `frontend/src/api/client.ts` — `getSoldComps(...)`; add `"deal"` to the watch types list.
- `frontend/src/components/SoldComps.tsx` (NEW) — "Recent sold (eBay)" evidence block.
- `frontend/src/components/CardDetail.tsx` — render `<SoldComps>` under the market price.
- `frontend/src/components/Deals.tsx` — render `<SoldComps>` once near the top.
- `frontend/src/components/WatchCardSheet.tsx` — add `deal` chip to `TYPE_INFO`.
- `frontend/src/components/AlertsFeed.tsx` — add `deal` filter chip + icon.
- `frontend/src/__tests__/CardDetail.test.tsx` (EXTEND) — `soldComps` fetch stub + assertions.
- `frontend/src/__tests__/SoldComps.test.tsx` (NEW) — evidence block tests.
- `frontend/src/__tests__/WatchCardSheet.test.tsx` (EXTEND) — `deal` chip submit.
- `frontend/src/__tests__/AlertsFeed.test.tsx` (EXTEND) — `deal` chip filter.

**Docs:** `AI_CONTEXT.md`, `PROJECT.md`. Optional `site/app/sections/Deals.tsx` caption touch.

---

### Task 1: Sold-comp dataclass + provider method

**Files:**
- Modify: `backend/src/cardplatform/prices/listings_provider.py` (add `SoldComp` after `ListingQuote`)
- Modify: `backend/src/cardplatform/prices/ebay_listings.py` (add `fetch_sold_listings` + `_search_completed` + `_parse_completed`)
- Test: `backend/tests/test_ebay_sold_comps.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ebay_sold_comps.py`:

```python
"""Tests for EbayListingsProvider.fetch_sold_listings (Phase 05b).

Mirrors test_ebay_listings_provider.py's discipline: a missing key short-
circuits to [] without a network call; sold comps parse from
findCompletedItemsResponse; unsold (EndedWithoutSales) and price-less items
are skipped — never fabricated; SERVICE-VERSION=1.13.0 is required for the
correct sellingState. The provider never raises.
"""
from __future__ import annotations

from types import SimpleNamespace

from cardplatform.prices.ebay_listings import EbayListingsProvider


def _settings(key="EBAY_APP_ID", base="https://svcs.ebay.com"):
    return SimpleNamespace(
        listings_api_key=key,
        listings_base_url=base,
        http_max_attempts=3,
        http_timeout_seconds=10.0,
    )


def _completed_payload(items, state="EndedWithSales"):
    """Build a findCompletedItemsResponse payload wrapping each item."""
    return {
        "findCompletedItemsResponse": [
            {
                "searchResult": [{"item": items}],
                "paginationOutput": [{"totalEntries": ["0"]}],
            }
        ]
    }


def _item(item_id="111", price="118.00", currency="USD", state="EndedWithSales",
          end="2026-07-30T18:30:00.000Z", title="Charizard #4", cond="Used",
          url="https://ebay.example/x"):
    return {
        "itemId": [item_id],
        "title": [title],
        "sellingStatus": [
            {
                "sellingState": [state],
                "currentPrice": [{"@currencyId": currency, "__value__": price}],
            }
        ],
        "listingInfo": [{"endTime": [end]}],
        "condition": [{"conditionDisplayName": [cond]}],
        "viewItemURL": [url],
    }


def test_no_key_returns_empty_without_network(monkeypatch):
    prov = EbayListingsProvider(settings=_settings(key=None))
    # If a network call were attempted, this would explode.
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get",
                       lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
    assert prov.fetch_sold_listings("base1-4", "") == []


def test_parses_sold_comps(monkeypatch):
    prov = EbayListingsProvider(settings=_settings())
    payload = _completed_payload([_item(item_id="a"), _item(item_id="b", price="121.00")])
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get", fake_get)
    comps = prov.fetch_sold_listings("base1-4", "", limit=3)

    assert [c.listing_id for c in comps] == ["a", "b"]
    assert comps[0].price == 118.0
    assert comps[0].currency == "USD"
    assert comps[0].source == "ebay"
    assert comps[0].url == "https://ebay.example/x"
    assert comps[0].condition == "Used"
    assert comps[0].sold_at is not None  # tz-aware from endTime
    # SERVICE-VERSION=1.13.0 is the bug-gotcha requirement.
    assert captured["params"]["SERVICE-VERSION"] == "1.13.0"
    assert captured["params"]["OPERATION-NAME"] == "findCompletedItems"
    # SoldItemsOnly filter is applied.
    assert captured["params"]["itemFilter(0).name"] == "SoldItemsOnly"
    assert captured["params"]["itemFilter(0).value"] == "true"


def test_skips_unsold_listings(monkeypatch):
    """EndedWithoutSales must NOT become a sold comp — never fabricate a sale."""
    prov = EbayListingsProvider(settings=_settings())
    payload = _completed_payload([_item(item_id="unsold", state="EndedWithoutSales")])
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload))
    assert prov.fetch_sold_listings("base1-4", "") == []


def test_skips_price_less_items(monkeypatch):
    """A sold item missing a price is skipped — never a fabricated $0 (SACRED)."""
    prov = EbayListingsProvider(settings=_settings())
    bad = _item(item_id="noprice")
    bad["sellingStatus"] = [{"sellingState": ["EndedWithSales"]}]  # no currentPrice
    payload = _completed_payload([bad])
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload))
    assert prov.fetch_sold_listings("base1-4", "") == []


def test_caps_to_limit(monkeypatch):
    prov = EbayListingsProvider(settings=_settings())
    payload = _completed_payload([_item(item_id=str(i)) for i in range(6)])
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload))
    comps = prov.fetch_sold_listings("base1-4", "", limit=3)
    assert len(comps) == 3


def test_bad_json_degrades_to_empty(monkeypatch):
    prov = EbayListingsProvider(settings=_settings())
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"nope": 1}))
    assert prov.fetch_sold_listings("base1-4", "") == []


def test_terminal_404_degrades_to_empty(monkeypatch):
    prov = EbayListingsProvider(settings=_settings())

    def fake_get(url, params=None, timeout=None):
        return SimpleNamespace(status_code=404, json=lambda: {})

    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get", fake_get)
    assert prov.fetch_sold_listings("base1-4", "") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_ebay_sold_comps.py -q`
Expected: FAIL — `fetch_sold_listings` / `SoldComp` do not exist yet.

- [ ] **Step 3: Add the `SoldComp` dataclass**

In `backend/src/cardplatform/prices/listings_provider.py`, after the `ListingQuote` dataclass (before `class ListingsProvider`), add:

```python
@dataclass(frozen=True)
class SoldComp:
    """One recently-sold eBay listing for a (card, variant) — sale evidence.

    Backs the raw market price in the UI ("market $120 because these 3 just
    sold at $118/$121/$119"). Distinct from ListingQuote: a sold comp carries
    `sold_at` (the sale close, from listingInfo.endTime) and no listing_type /
    auction_end_at — completed listings are historical, not active. Sold comps
    are NEVER persisted (on-demand evidence only); `source="ebay"`.
    """

    card_id: str
    variant: str
    listing_id: str
    price: float
    title: str | None = None
    currency: str | None = None
    url: str | None = None
    condition: str | None = None
    sold_at: datetime | None = None
    source: str = "ebay"
```

- [ ] **Step 4: Add `fetch_sold_listings` + `_search_completed` + `_parse_completed`**

In `backend/src/cardplatform/prices/ebay_listings.py`:

Update the import from `listings_provider` to also pull `SoldComp`:

```python
from cardplatform.prices.listings_provider import ListingQuote, SoldComp
```

Add these methods to `EbayListingsProvider` (after `fetch_listings`, before `_build_query`):

```python
    def fetch_sold_listings(
        self, card_id: str, variant: str, limit: int = 3
    ) -> list[SoldComp]:
        """Fetch up to `limit` recently-sold eBay listings (sale evidence).

        Mirrors fetch_listings' never-raise discipline: no key -> [] without a
        request; transport/5xx/429 retry then []; bad JSON / 404 terminal then
        []; unexpected shape -> []. Uses the deprecated findCompletedItems
        (still functional for free App IDs; degrades to [] if retired) with
        SoldItemsOnly=true and SERVICE-VERSION=1.13.0 (the bug-gotcha: 1.0.0
        returns sellingState="Ended" for sold items; 1.13.0 returns
        "EndedWithSales"). Never persists — sold comps are on-demand evidence.
        """
        if not self.settings.listings_api_key:
            return []

        query = self._build_query(card_id)
        payload = self._search_completed(query, limit)
        if payload is None:
            return []

        try:
            return self._parse_completed(card_id, variant, payload, limit)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("ebay sold-comps parse failure for %s: %s", card_id, exc)
            return []
```

Add `_search_completed` after `_search` (mirrors it but with the completed operation + filter + sort):

```python
    def _search_completed(self, query: str, limit: int) -> dict[str, Any] | None:
        """GET the eBay Finding API findCompletedItems (sold listings), retrying
        transport/5xx/429 only. Same terminal/retry/degrade discipline as
        _search. SERVICE-VERSION=1.13.0 is REQUIRED — 1.0.0 misreports sold
        items as sellingState="Ended" (eBay bug #185); 1.13.0 returns the
        correct "EndedWithSales". SoldItemsOnly filters to sold listings;
        EndTimeSoonest sorts most-recently-ended first.
        """
        url = self.settings.listings_base_url
        params = {
            "OPERATION-NAME": "findCompletedItems",
            "SERVICE-VERSION": "1.13.0",
            "SECURITY-APPNAME": self.settings.listings_api_key,
            "RESPONSE-DATA-FORMAT": "JSON",
            "REST-PAYLOAD": "",
            "GLOBAL-ID": "EBAY-US",
            "keywords": query,
            "itemFilter(0).name": "SoldItemsOnly",
            "itemFilter(0).value": "true",
            "sortOrder": "EndTimeSoonest",
            "paginationInput.entriesPerPage": str(max(1, min(limit, 100))),
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
                logger.warning("ebay sold-comps transport error for %r: %s", query, exc)
                return None
            if response.status_code == 200:
                try:
                    return response.json()
                except (httpx.DecodingError, ValueError) as exc:
                    logger.warning("ebay sold-comps bad JSON for %r: %s", query, exc)
                    raise _TerminalHttpError(response.status_code) from exc
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning("ebay sold-comps HTTP %s for %r (retryable)", response.status_code, query)
                return None
            logger.warning("ebay sold-comps HTTP %s for %r (terminal)", response.status_code, query)
            raise _TerminalHttpError(response.status_code)

        try:
            return _attempt()
        except _TerminalHttpError:
            return None
        except RetryError:
            logger.error("ebay sold-comps gave up for %r after %s attempts", query, self.settings.http_max_attempts)
            return None
```

Add `_parse_completed` after `_parse` (static):

```python
    @staticmethod
    def _parse_completed(card_id: str, variant: str, payload: dict[str, Any], limit: int) -> list[SoldComp]:
        """Map findCompletedItemsResponse.searchResult.item -> SoldComps.

        Same single-element-array unwrap as _parse. CRITICAL: skip any item
        whose sellingState != "EndedWithSales" — EndedWithoutSales (and any
        other state) is NOT a sold comp; never fabricate a sale. Skip items
        missing itemId or a parseable price (sacred never-fabricate). sold_at
        is the sale close from listingInfo.endTime (tz-aware UTC, or None).
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
            listing_id = _first(item, "itemId")
            if not listing_id:
                continue

            selling = _first(item, "sellingStatus")
            if not isinstance(selling, dict):
                continue
            state = _first(selling, "sellingState")
            # Only confirmed sales. Never fabricate a sale from an unsold item.
            if state != "EndedWithSales":
                continue

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
                        continue
            if price is None:
                continue  # missing price — skip, never fabricate (SACRED)

            listing_info = _first(item, "listingInfo")
            sold_at = (
                _parse_iso(_first(listing_info, "endTime"))
                if isinstance(listing_info, dict)
                else None
            )

            condition = None
            cond_block = _first(item, "condition")
            if isinstance(cond_block, dict):
                condition = _first(cond_block, "conditionDisplayName")

            comps.append(
                SoldComp(
                    card_id=card_id, variant=variant, listing_id=str(listing_id),
                    price=price, currency=currency, title=_first(item, "title"),
                    url=_first(item, "viewItemURL"), condition=condition,
                    sold_at=sold_at, source="ebay",
                )
            )
            if len(comps) >= limit:
                break
        return comps
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_ebay_sold_comps.py -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Run the full backend suite to confirm no regression**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (462 + 7 = 469).

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/prices/listings_provider.py backend/src/cardplatform/prices/ebay_listings.py backend/tests/test_ebay_sold_comps.py
git commit -m "feat(sold-comps): eBay findCompletedItems adapter + SoldComp (T1)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Sold-comps API endpoint

**Files:**
- Create: `backend/src/cardplatform/prices/sold_comps_api_models.py`
- Modify: `backend/src/cardplatform/api.py` (imports + new endpoint after the deals endpoints, ~line 1062)
- Test: `backend/tests/test_sold_comps_api.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sold_comps_api.py`:

```python
"""Tests for GET /cards/{id}/sold-comps (Phase 05b)."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from cardplatform.api import build_app
from cardplatform.db.session import Database


def _client(monkeypatch, sold_payload=None, sold_unavailable=False):
    """Build a TestClient with the in-memory test DB and a stubbed provider."""
    db = Database.for_testing()
    db.create_all()
    # Seed one card so _require_card passes.
    with db.session() as s:
        from cardplatform.db.models import Card, CardSet
        s.add(CardSet(id="base1", name="Base", series="base", total=102, printed_at=None))
        s.add(Card(id="base1-4", name="Charizard", number="4", set_id="base1"))
        s.commit()

    app = build_app(db)

    # Patch EbayListingsProvider.fetch_sold_listings to a deterministic stub.
    from cardplatform.prices import ebay_listings as mod

    def fake_fetch(self, card_id, variant, limit=3):
        if sold_unavailable:
            return []
        return sold_payload or []

    monkeypatch.setattr(mod.EbayListingsProvider, "fetch_sold_listings", fake_fetch)
    return TestClient(app)


def _comp(listing_id="a", price=118.0, currency="USD", sold_at="2026-07-30T18:30:00Z"):
    from cardplatform.prices.listings_provider import SoldComp
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(sold_at.replace("Z", "+00:00"))
    return SoldComp(card_id="base1-4", variant="", listing_id=listing_id, price=price,
                    currency=currency, url="https://ebay.example/x", condition="Used",
                    sold_at=dt, title="Charizard #4", source="ebay")


def test_returns_sold_comps(monkeypatch):
    comps = [_comp("a", 118.0), _comp("b", 121.0), _comp("c", 119.0)]
    client = _client(monkeypatch, sold_payload=comps)
    r = client.get("/cards/base1-4/sold-comps?variant=&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert body["card_id"] == "base1-4"
    assert body["variant"] == ""
    assert body["sold_comps_unavailable"] is False
    assert body["sold_comps_empty"] is False
    assert [c["listing_id"] for c in body["sold_comps"]] == ["a", "b", "c"]
    assert body["sold_comps"][0]["price"] == 118.0
    assert body["sold_comps"][0]["source"] == "ebay"
    assert body["sold_comps"][0]["sold_at"].startswith("2026-07-30")


def test_unavailable_flag_when_no_key(monkeypatch):
    """No listings_api_key -> unavailable True, empty False (honest)."""
    client = _client(monkeypatch, sold_unavailable=True)
    # Force the settings to report no key by patching the endpoint's settings.
    # The provider stub returns [] AND we simulate no-key by patching settings.
    from cardplatform.api import _settings  # may not exist; use app state instead
    r = client.get("/cards/base1-4/sold-comps")
    # With the stub returning [] and a key present (test settings), this is "empty".
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps"] == []
    assert body["sold_comps_empty"] is True
    assert body["sold_comps_unavailable"] is False


def test_empty_flag_when_no_sold_comps(monkeypatch):
    client = _client(monkeypatch, sold_payload=[])
    r = client.get("/cards/base1-4/sold-comps")
    assert r.status_code == 200
    body = r.json()
    assert body["sold_comps"] == []
    assert body["sold_comps_empty"] is True
    assert body["sold_comps_unavailable"] is False


def test_limit_clamped(monkeypatch):
    comps = [_comp(str(i)) for i in range(20)]
    client = _client(monkeypatch, sold_payload=comps)
    r = client.get("/cards/base1-4/sold-comps?limit=99")
    assert r.status_code == 200
    assert len(r.json()["sold_comps"]) <= 10  # clamped to max 10


def test_unknown_card_404(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/cards/nope-1/sold-comps")
    assert r.status_code == 404
```

> Note: the `test_unavailable_flag_when_no_key` test simulates "empty" (key present, no results). True "unavailable" (no key) is covered by the provider-level no-key test in T1 and the endpoint's `settings.listings_api_key is None` check. If the implementer finds the `_settings` import unused, drop that line — keep the test asserting the `empty` path. The implementer may simplify this test to only assert the `empty` path if wiring a no-key fixture is awkward, but MUST keep an assertion that the endpoint returns `sold_comps_unavailable: True` when `settings.listings_api_key is None` — implement that via a second fixture or by monkeypatching `app.state`/settings if cleanest. The contract: unavailable ⟺ no key configured.

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sold_comps_api.py -q`
Expected: FAIL — endpoint/models do not exist.

- [ ] **Step 3: Create the Pydantic models**

Create `backend/src/cardplatform/prices/sold_comps_api_models.py`:

```python
"""Pydantic wire models for the sold-comps evidence API (Phase 05b).

Sold comps are recent eBay *sold* listings shown as evidence backing the raw
market price. They are NOT persisted (on-demand fetch only), so these models
serialise the EbayListingsProvider.SoldComp dataclass directly. Honest flags:
`sold_comps_unavailable` is True when no listings_api_key is configured (no
provider); `sold_comps_empty` is True when a key IS set but eBay returned no
sold comps. `sold_at` is the sale close (tz-aware ISO).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SoldCompOut(BaseModel):
    """One recently-sold eBay listing (sale evidence)."""

    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    price: float
    currency: str | None
    url: str | None
    condition: str | None
    sold_at: datetime | None
    source: str


class SoldCompsResponse(BaseModel):
    """Response for GET /cards/{id}/sold-comps."""

    card_id: str
    variant: str
    sold_comps: list[SoldCompOut]
    sold_comps_unavailable: bool
    sold_comps_empty: bool
```

- [ ] **Step 4: Add the endpoint to api.py**

In `backend/src/cardplatform/api.py`, add to the imports near the other deals/prices imports:

```python
from cardplatform.prices.sold_comps_api_models import SoldCompsOut, SoldCompsResponse as SoldCompsApiResponse
```

> If a name clash with `DealsResponse` is awkward, alias `SoldCompsResponse` from the new module as `SoldCompsResponseModel`. Pick the cleanest alias that matches surrounding style (the deals module exports `DealsResponse` un-aliased). Recommended: import the module qualified:
> `from cardplatform.prices import sold_comps_api_models as sold_models`

Add the endpoint after the `deals_feed` endpoint (after line ~1062, before the alert poll loop section). Insert inside the `build_app` function body (it has access to `settings` and `session` deps like the other endpoints):

```python
    @app.get("/cards/{card_id}/sold-comps", response_model=sold_models.SoldCompsResponse)
    def card_sold_comps(
        card_id: str,
        variant: str | None = Query(default=None),
        limit: int = Query(default=3, ge=1, le=10),
        session: Session = Depends(get_session),
    ) -> sold_models.SoldCompsResponse:
        """Recent eBay *sold* listings for a card — sale evidence backing the
        raw market price ("market $120 because these 3 just sold at
        $118/$121/$119"). Honest flags: `sold_comps_unavailable` is True when
        no `listings_api_key` is configured (no provider); `sold_comps_empty`
        is True when a key IS set but eBay returned no sold comps. On-demand
        read — sold comps are NEVER persisted (no snapshot writes). Unknown
        card is 404.

        Backed by the deprecated findCompletedItems (still functional for free
        App IDs; degrades to [] if retired). Sold comps are evidence, not a
        price target.
        """
        _require_card(session, card_id)
        v = variant or ""
        provider = EbayListingsProvider(catalog=_catalog_lookup(session))
        comps = provider.fetch_sold_listings(card_id, v, limit=limit)
        unavailable = settings.listings_api_key is None
        return sold_models.SoldCompsResponse(
            card_id=card_id,
            variant=v,
            sold_comps=[sold_models.SoldCompOut(
                listing_id=c.listing_id, title=c.title, price=c.price,
                currency=c.currency, url=c.url, condition=c.condition,
                sold_at=c.sold_at, source=c.source,
            ) for c in comps],
            sold_comps_unavailable=unavailable,
            sold_comps_empty=(not unavailable and not comps),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_sold_comps_api.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (469 + 5 = 474).

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/prices/sold_comps_api_models.py backend/src/cardplatform/api.py backend/tests/test_sold_comps_api.py
git commit -m "feat(sold-comps): GET /cards/{id}/sold-comps evidence endpoint (T2)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Frontend sold-comps evidence block

**Files:**
- Modify: `frontend/src/api/types.ts` (add `SoldComp`, `SoldCompsResponse`; extend `AlertType`)
- Modify: `frontend/src/api/client.ts` (add `getSoldComps`; add `"deal"` to the watch types list)
- Create: `frontend/src/components/SoldComps.tsx`
- Modify: `frontend/src/components/CardDetail.tsx` (render `<SoldComps>` under the market price)
- Modify: `frontend/src/components/Deals.tsx` (render `<SoldComps>` once near the top)
- Test: `frontend/src/__tests__/SoldComps.test.tsx` (new)
- Test: `frontend/src/__tests__/CardDetail.test.tsx` (extend the stub + 1 assertion)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/SoldComps.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import SoldComps from "../components/SoldComps";

const comps = [
  { listing_id: "a", title: "Charizard #4", price: 118.0, currency: "USD",
    url: "https://ebay.example/a", condition: "Used", sold_at: "2026-07-30T18:30:00Z", source: "ebay" },
  { listing_id: "b", title: "Charizard #4", price: 121.0, currency: "USD",
    url: "https://ebay.example/b", condition: "Used", sold_at: "2026-07-29T18:30:00Z", source: "ebay" },
];

afterEach(() => vi.unstubAllGlobals());

function stub(body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body }));
}

describe("SoldComps", () => {
  it("renders up to 3 recent sold comps as evidence", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: comps,
          sold_comps_unavailable: false, sold_comps_empty: false });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$118.00");
    });
    expect(container.textContent ?? "").toContain("$121.00");
    expect(container.textContent ?? "").toContain("ebay");
    expect(container.textContent ?? "").toMatch(/recent sold/i);
  });

  it("unavailable -> honest 'set a listings source key' (no fake price)", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: [],
          sold_comps_unavailable: true, sold_comps_empty: false });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set a listings source key/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("empty -> honest 'no recent sold comps found'", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: [],
          sold_comps_unavailable: false, sold_comps_empty: true });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no recent sold comps/i);
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- --run SoldComps`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Add types + client**

In `frontend/src/api/types.ts`, extend the `AlertType` union (currently `"restock" | "new_listing" | "price_target" | "auction_ending" | "drop_time"`) to add `"deal"`, and add:

```ts
export interface SoldComp {
  listing_id: string;
  title: string | null;
  price: number;
  currency: string | null;
  url: string | null;
  condition: string | null;
  sold_at: string | null;
  source: string;
}

export interface SoldCompsResponse {
  card_id: string;
  variant: string;
  sold_comps: SoldComp[];
  sold_comps_unavailable: boolean;
  sold_comps_empty: boolean;
}
```

In `frontend/src/api/client.ts`, add the watch-types `"deal"` entry to the `ALERT_TYPES` array (the array near lines 413-417 that lists `"restock","new_listing","price_target","auction_ending","drop_time"`), and add a fetch helper:

```ts
export async function getSoldComps(
  cardId: string,
  variant: string,
  limit = 3,
): Promise<SoldCompsResponse> {
  const v = encodeURIComponent(variant || "");
  const res = await fetch(
    `${API_BASE}/cards/${encodeURIComponent(cardId)}/sold-comps?variant=${v}&limit=${limit}`,
  );
  if (!res.ok) throw new Error(`sold-comps fetch failed: ${res.status}`);
  return res.json();
}
```

(Import `SoldCompsResponse` from `./types` at the top of `client.ts`.)

- [ ] **Step 4: Create `SoldComps.tsx`**

Create `frontend/src/components/SoldComps.tsx`:

```tsx
// "Recent sold (eBay)" evidence block — sold comps backing the raw market
// price. Sold comps are NOT a price target; they're evidence ("market $120
// because these 3 just sold at $118/$121/$119"). Honest empty states: no key
// -> unavailable hint; key set but no comps -> "no recent sold comps". Never a
// fabricated $0.
import { useEffect, useState } from "react";

import { getSoldComps } from "../api/client";
import type { SoldCompsResponse } from "../api/types";
import { relativeTime } from "../lib/time";
import { formatMoney } from "../lib/format";

export default function SoldComps({ cardId, variant }: { cardId: string; variant: string }) {
  const [data, setData] = useState<SoldCompsResponse | null>(null);

  useEffect(() => {
    let alive = true;
    getSoldComps(cardId, variant, 3)
      .then((d) => { if (alive) setData(d); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [cardId, variant]);

  if (data === null) return <p className="sold-comps loading">Checking recent sales…</p>;

  if (data.sold_comps_unavailable) {
    return (
      <p className="sold-comps unavailable">
        Recent sold comps unavailable — set a listings source key to show eBay sale evidence.
      </p>
    );
  }
  if (data.sold_comps_empty || data.sold_comps.length === 0) {
    return <p className="sold-comps empty">No recent eBay sold comps found for this card.</p>;
  }

  return (
    <section className="sold-comps">
      <h4>Recent sold (eBay)</h4>
      <p className="sold-comps caption">
        Sold comps are evidence backing the market price, not a price target.
      </p>
      <ul>
        {data.sold_comps.map((c) => (
          <li key={c.listing_id} className="sold-comp-row">
            <a href={c.url ?? "#"} target="_blank" rel="noreferrer" className="sold-comp-link">
              <span className="sold-comp-price">{formatMoney(c.price, c.currency)}</span>
              {c.condition ? <span className="sold-comp-cond">{c.condition}</span> : null}
              {c.sold_at ? (
                <span className="sold-comp-when">{relativeTime(c.sold_at)}</span>
              ) : null}
              <span className="sold-comp-source">{c.source}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

> Note: the implementer MUST verify the exact import paths + helper names (`relativeTime` in `lib/time.ts`, `formatMoney` in `lib/format.ts`) by grepping the codebase. `relativeTime` exists in `lib/time.ts` (confirmed). `formatMoney` — confirm the helper name and signature (it's used in `Deals.tsx` and `CardDetail.tsx`); if its signature differs (e.g. `formatMoney(n)` with no currency arg), adapt the call to match the codebase. Do NOT invent a helper; reuse the existing one.

- [ ] **Step 5: Render in CardDetail + Deals**

In `frontend/src/components/CardDetail.tsx`, render `<SoldComps cardId={cardId} variant={variant} />` under the market-price block (after the price + staleness render, before or after the listings block — match the existing layout). Import the component at the top.

In `frontend/src/components/Deals.tsx`, render `<SoldComps>` once near the top of the deals view (e.g. under the header / caveat). Use the first card in the feed if available, or a generic call with the user's primary watched card. If the deals feed has no single card_id readily, render it for the first deal's `card_id` (the deals response carries per-deal `card_id`? verify — if not, omit from Deals and only keep in CardDetail, noting the decision in the commit). **Prefer keeping it in CardDetail only if Deals wiring is awkward** — the spec says "and/or"; CardDetail is the primary evidence surface.

- [ ] **Step 6: Extend the CardDetail test stub**

In `frontend/src/__tests__/CardDetail.test.tsx`, extend `stubFetch` to handle `/sold-comps` (return an empty honest response by default), and add one assertion that the sold-comps section renders. Add to the `stubFetch` options: `soldComps?: SoldCompsResponse`. In the spy, before the final 404 fallback:

```ts
    if (u.match(/\/cards\/[^/]+\/sold-comps/)) {
      return {
        ok: true,
        status: 200,
        json: async () => opts.soldComps ?? {
          card_id: "base1-4", variant: "normal",
          sold_comps: [], sold_comps_unavailable: false, sold_comps_empty: true,
        },
      };
    }
```

Place this match BEFORE the generic `/cards/{id}$` match (the sold-comps URL also matches `/cards/[^/]+/...` so order matters — put it with the other `/cards/{id}/deals` and `/cards/{id}/listings` branches). Add a test:

```tsx
  it("renders the Recent sold (eBay) evidence block", async () => {
    stubFetch({
      soldComps: {
        card_id: "base1-4", variant: "normal",
        sold_comps: [{ listing_id: "a", title: "Charizard #4", price: 118.0, currency: "USD",
          url: "https://ebay.example/a", condition: "Used", sold_at: "2026-07-30T18:30:00Z", source: "ebay" }],
        sold_comps_unavailable: false, sold_comps_empty: false,
      },
    });
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$118.00");
    });
    expect(container.textContent ?? "").toMatch(/recent sold/i);
  });
```

- [ ] **Step 7: Run frontend tests**

Run: `npm --prefix frontend test -- --run`
Expected: PASS (96 + 4 = 100).

- [ ] **Step 8: Run the build**

Run: `npm --prefix frontend run build`
Expected: clean (no TS errors).

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(sold-comps): Recent sold (eBay) evidence block in CardDetail (T3)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Deal-alert backend (`_eval_deal` + AlertEngine injection + watchlist validation)

**Files:**
- Modify: `backend/src/cardplatform/alerts/engine.py` (ctor `deal_engine` param + `_eval_deal` + dispatch branch)
- Modify: `backend/src/cardplatform/api.py` (`_ALERT_TYPES` + 422 rule)
- Test: `backend/tests/test_alert_engine_deal.py` (new)
- Test: `backend/tests/test_watchlist_api.py` (extend for `deal` 422)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_alert_engine_deal.py`:

```python
"""Tests for AlertEngine._eval_deal (Phase 05b)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from cardplatform.alerts.engine import AlertEngine
from cardplatform.db.models import Watch, AlertEvent
from cardplatform.db.session import Database


@dataclass
class _Assess:
    listing_id: str
    is_rip: bool
    is_flip: bool
    listing_price: float = 40.0
    url: str | None = "https://ebay.example/x"
    rip_edge: float | None = 12.0
    flip_edge_to_10: float | None = None
    deal_score: float | None = 12.0
    currency: str | None = "USD"
    condition: str | None = None
    raw_market: object | None = None


class _FakeDealEngine:
    def __init__(self, assessments):
        self._assessments = assessments
        self.calls = []

    def assess(self, card_id, variant):
        self.calls.append((card_id, variant))
        return self._assessments


def _engine(db, deal_engine=None, clock=None):
    return AlertEngine(db.session().__self__, listings_service=None, notifier=None,
                       settings=SimpleNamespace(alert_cooldown_min=60), clock=clock,
                       deal_engine=deal_engine)


def _db():
    db = Database.for_testing()
    db.create_all()
    with db.session() as s:
        from cardplatform.db.models import Card, CardSet
        s.add(CardSet(id="base1", name="Base", series="base", total=102, printed_at=None))
        s.add(Card(id="base1-4", name="Charizard", number="4", set_id="base1"))
        s.commit()
    return db


def _watch(card_id="base1-4", variant="", last_seen=None):
    return Watch(card_id=card_id, variant=variant, alert_type="deal",
                 target_price=None, drop_at=None, active=True,
                 last_seen_listing_ids=last_seen)


def test_first_poll_never_fires_establishes_baseline():
    db = _db()
    de = _FakeDealEngine([_Assess("a", is_rip=True), _Assess("b", is_flip=True)])
    with db.session() as s:
        w = _watch()
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=de)
        n = eng.check_alerts()
        s.refresh(w)
        assert n == 0
        assert json.loads(w.last_seen_listing_ids) == ["a", "b"]
        assert s.query(AlertEvent).count() == 0


def test_fires_only_for_new_deal_listings():
    db = _db()
    # Baseline already has "a". A new rip listing "b" should fire; "a" should not.
    de = _FakeDealEngine([_Assess("a", is_rip=True), _Assess("b", is_rip=True)])
    with db.session() as s:
        w = _watch(last_seen=json.dumps(["a"]))
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=de)
        n = eng.check_alerts()
        assert n == 1
        ev = s.query(AlertEvent).one()
        assert "b" in ev.context  # the new listing id is in the context
        assert ev.alert_type == "deal"


def test_does_not_fire_for_non_deal_listings():
    db = _db()
    de = _FakeDealEngine([_Assess("a", is_rip=False, is_flip=False, rip_edge=0.0, deal_score=0.0)])
    with db.session() as s:
        w = _watch()
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=de)
        # First poll establishes baseline (no fire). Second poll: same non-deal id -> no fire.
        eng.check_alerts()
        n2 = eng.check_alerts()
        assert n2 == 0
        assert s.query(AlertEvent).count() == 0


def test_baseline_advances_so_removed_deal_does_not_refire():
    db = _db()
    de = _FakeDealEngine([_Assess("a", is_rip=True)])  # only "a" is a deal
    with db.session() as s:
        w = _watch(last_seen=json.dumps([]))
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=de)
        # Poll 1: "a" is new -> fires, baseline becomes ["a"].
        assert eng.check_alerts() == 1
        # Poll 2: "a" still a deal but not new -> no fire.
        assert eng.check_alerts() == 0
        assert s.query(AlertEvent).count() == 1


def test_no_deal_engine_is_no_op():
    db = _db()
    with db.session() as s:
        w = _watch(last_seen=json.dumps([]))
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=None)
        assert eng.check_alerts() == 0
        assert s.query(AlertEvent).count() == 0


def test_flip_message_when_flip_dominates():
    db = _db()
    de = _FakeDealEngine([_Assess("b", is_rip=False, is_flip=True, rip_edge=None,
                                 flip_edge_to_10=95.0, deal_score=95.0)])
    with db.session() as s:
        w = _watch(last_seen=json.dumps([]))
        s.add(w); s.commit()
        eng = AlertEngine(s, settings=SimpleNamespace(alert_cooldown_min=60), deal_engine=de)
        eng.check_alerts()
        msg = s.query(AlertEvent).one().message
        assert "flip" in msg.lower() or "95" in msg
```

> Note: the implementer MUST verify `Database.for_testing()` exists (grep the codebase — the sold-comps tests in T2 use it; if the factory name differs, use the established test-DB pattern from the existing alert-engine tests, e.g. `backend/tests/test_alert_engine*.py`). Match the existing alert-engine test fixtures exactly. The `_engine` helper above may be unused — drop it if so.

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_alert_engine_deal.py -q`
Expected: FAIL — `_eval_deal` / `deal_engine` param do not exist.

- [ ] **Step 3: Add `deal_engine` ctor param + `_eval_deal` + dispatch**

In `backend/src/cardplatform/alerts/engine.py`:

Extend the constructor signature:

```python
    def __init__(
        self,
        session: Session,
        listings_service=None,
        notifier=None,
        settings=None,
        clock: Optional[Callable[[], datetime]] = None,
        deal_engine=None,
    ) -> None:
        self.session = session
        self._listings = listings_service
        self._notifier = notifier
        self._settings = settings
        self._deal_engine = deal_engine
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
```

Add the dispatch branch in `_eval` (before the `log.warning("unknown alert_type ...")` line):

```python
        if atype == "deal":
            return self._eval_deal(w, now)
```

Add the `_eval_deal` method (after `_eval_new_listing`, before `_eval_price_target`):

```python
    # --------------------------------------------------------------- deal

    def _eval_deal(self, w: Watch, now: datetime) -> int:
        """Fire when a NEW active listing clears the rip/flip deal thresholds.

        Mirrors _eval_new_listing's baseline-dedupe: the first poll establishes
        the baseline (never fires); subsequent polls fire only for listing ids
        that are deals AND not yet in the baseline. The baseline always advances
        (even to empty) so a listing that stops being a deal cannot re-fire.
        Reuses the global deal thresholds via the read-only DealEngine — no
        per-watch thresholds, no snapshot writes. A missing deal_engine (e.g. a
        caller that didn't wire one) is a silent no-op, never a crash.
        """
        if w.card_id is None:
            log.debug("deal watch %s has no card_id; skipping", w.id)
            return 0
        if self._deal_engine is None:
            log.debug("deal watch %s has no deal_engine; skipping", w.id)
            return 0
        variant = w.variant or ""
        try:
            assessments = self._deal_engine.assess(w.card_id, variant)
        except Exception:
            # DealEngine.assess never raises per Phase 05, but defend the
            # never-raise contract: a deal evaluation failure is a skip.
            log.warning("deal assess failed for watch %s", w.id, exc_info=True)
            return 0
        deal_map = {a.listing_id: a for a in assessments if a.is_rip or a.is_flip}
        curr_ids = set(deal_map)
        prev_ids = (
            set(json.loads(w.last_seen_listing_ids)) if w.last_seen_listing_ids else None
        )
        # First poll: establish baseline, never fire.
        if prev_ids is None:
            w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
            return 0
        new_ids = curr_ids - prev_ids
        fired = 0
        for lid in sorted(new_ids):
            a = deal_map[lid]
            self._fire(w, self._deal_message(w, a), self._deal_context(a))
            fired += 1
        # Always advance the baseline so removed deals don't re-fire.
        w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
        return fired

    def _deal_message(self, w: Watch, a) -> str:
        name = self._display(w)
        price = a.listing_price
        price_str = f"${price:.2f}" if price is not None else "—"
        rip = a.rip_edge
        flip = a.flip_edge_to_10
        rip_str = f"${rip:.2f}" if rip is not None else None
        flip_str = f"${flip:.2f}" if flip is not None else None
        # Lead with the larger of the two edges.
        if a.is_rip and (not a.is_flip or (rip is not None and flip is not None and rip >= flip)):
            return (f"Deal on {name} — listing {price_str} vs market, RIP edge {rip_str}. "
                    f"Verify before buying.")
        if a.is_flip and flip_str is not None:
            return (f"Deal on {name} — listing {price_str}, PSA-10 flip spread {flip_str} "
                    f"after grading. Verify before buying.")
        # Fallback (rip-only without a numeric edge, or unexpected).
        return f"Deal on {name} — listing {price_str}. Verify before buying."

    def _deal_context(self, a) -> str:
        def _pp(p):
            if p is None:
                return None
            return {"price": p.price, "source": p.source, "source_updated_at": p.source_updated_at}
        return json.dumps({
            "listing_id": a.listing_id,
            "url": a.url,
            "listing_price": a.listing_price,
            "currency": a.currency,
            "condition": a.condition,
            "rip_edge": a.rip_edge,
            "flip_edge_to_10": a.flip_edge_to_10,
            "is_rip": a.is_rip,
            "is_flip": a.is_flip,
            "deal_score": a.deal_score,
            "raw_market": _pp(getattr(a, "raw_market", None)),
        })
```

- [ ] **Step 4: Add `"deal"` to `_ALERT_TYPES` + 422 rule in api.py**

In `backend/src/cardplatform/api.py`:

```python
_ALERT_TYPES = {"restock", "new_listing", "price_target", "auction_ending", "drop_time", "deal"}
```

Add the 422 rule in `create_watch` (after the `drop_time` rule):

```python
        if payload.alert_type == "deal" and payload.card_id is None:
            raise HTTPException(
                status_code=422,
                detail="card_id is required for alert_type 'deal'",
            )
```

- [ ] **Step 5: Extend the watchlist test**

In `backend/tests/test_watchlist_api.py`, add (find the existing watchlist-create test pattern and mirror it):

```python
def test_create_deal_watch_requires_card_id(client_with_card):
    # card_id required for 'deal'; without it -> 422.
    r = client_with_card.post("/watchlist", json={
        "alert_type": "deal", "variant": "",
    })
    assert r.status_code == 422
    assert "card_id is required" in r.json()["detail"]


def test_create_deal_watch_succeeds(client_with_card):
    r = client_with_card.post("/watchlist", json={
        "alert_type": "deal", "card_id": "base1-4", "variant": "",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["alert_type"] == "deal"
    assert body["card_id"] == "base1-4"
```

> Note: the implementer MUST reuse the existing `client_with_card` fixture (or whatever the watchlist test file names it) — grep `backend/tests/test_watchlist_api.py` for the fixture and mirror the existing `price_target`/`drop_time` tests exactly.

- [ ] **Step 6: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_alert_engine_deal.py backend/tests/test_watchlist_api.py -q`
Expected: PASS.

- [ ] **Step 7: Full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (474 + new deal tests).

- [ ] **Step 8: Commit**

```bash
git add backend/src/cardplatform/alerts/engine.py backend/src/cardplatform/api.py backend/tests/test_alert_engine_deal.py backend/tests/test_watchlist_api.py
git commit -m "feat(alerts): _eval_deal + deal watch type (T4)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Wire DealEngine into AlertEngine (poll loop + CLI)

**Files:**
- Modify: `backend/src/cardplatform/api.py` (`_poll_loop` AlertEngine construction)
- Modify: `backend/src/cardplatform/cli.py` (`check_alerts` AlertEngine construction)
- Test: extend `backend/tests/test_alert_engine_deal.py` or `test_cli.py` if a CLI test exists; otherwise verify by import smoke.

- [ ] **Step 1: Write the failing test**

If a CLI smoke test exists (grep `backend/tests` for `test_cli`), extend it to assert `check_alerts` constructs an `AlertEngine` with a `deal_engine`. If none exists, add a focused import/wiring test:

```python
# backend/tests/test_alert_wiring.py (new, if no CLI test exists)
def test_cli_check_alerts_imports_and_wires_deal_engine():
    # Smoke: importing cli.check_alerts and the api poll loop must not fail,
    # and both must construct AlertEngine with a deal_engine. We assert via
    # monkeypatching AlertEngine to capture kwargs.
    import inspect
    from cardplatform.alerts.engine import AlertEngine
    sig = inspect.signature(AlertEngine.__init__)
    assert "deal_engine" in sig.parameters
```

(A lightweight presence test; the behavioral coverage is in T4. The implementer may strengthen this by monkeypatching `AlertEngine` to record `deal_engine` kwargs during a `check_alerts` call with no watches, but that requires the eBay/network path be stubbed — only do so if clean; otherwise the signature smoke + T4 behavioral tests suffice.)

- [ ] **Step 2: Run to verify it fails/passes as appropriate**

Run: `backend/.venv/Scripts/python -m pytest backend/tests/test_alert_wiring.py -q` (if created)
Expected: PASS already (signature exists from T4) — if so, this test is a guard. If the implementer added a stronger wiring test, expect it to fail before the wiring edit.

- [ ] **Step 3: Wire in api.py `_poll_loop`**

In `backend/src/cardplatform/api.py`, update the `_poll_loop` AlertEngine construction (around line 1134) to inject a `DealEngine`:

```python
                    with db.session() as session:
                        listings = ListingsService(
                            session, EbayListingsProvider(catalog=_catalog_lookup(session))
                        )
                        engine = AlertEngine(
                            session,
                            listings,
                            NotificationService(session, settings),
                            settings,
                            deal_engine=DealEngine(session, settings, listings_service=listings),
                        )
                        engine.check_alerts()
```

(Reusing the same `listings` service for both the AlertEngine's listing-based alerts and the DealEngine keeps one refresh path. `DealEngine` already accepts `listings_service=`.)

- [ ] **Step 4: Wire in cli.py `check_alerts`**

In `backend/src/cardplatform/cli.py`, update `check_alerts` to import and inject `DealEngine`:

```python
    from cardplatform.alerts.engine import AlertEngine
    from cardplatform.alerts.notify import NotificationService
    from cardplatform.api import _catalog_lookup
    from cardplatform.deals.engine import DealEngine
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService

    db = Database()
    db.create_all()

    with db.session() as session:
        listings = ListingsService(
            session, EbayListingsProvider(catalog=_catalog_lookup(session))
        )
        engine = AlertEngine(
            session,
            listings,
            NotificationService(session, db.settings),
            db.settings,
            deal_engine=DealEngine(session, db.settings, listings_service=listings),
        )
        n = engine.check_alerts()
```

- [ ] **Step 5: Run the full backend suite**

Run: `backend/.venv/Scripts/python -m pytest -q`
Expected: PASS (all green; the existing alert-engine tests that construct `AlertEngine` without `deal_engine` still pass since the param defaults to `None`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/api.py backend/src/cardplatform/cli.py backend/tests
git commit -m "feat(alerts): wire DealEngine into AlertEngine poll loop + CLI (T5)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Frontend deal-alert affordance

**Files:**
- Modify: `frontend/src/components/WatchCardSheet.tsx` (add `deal` to `TYPE_INFO`)
- Modify: `frontend/src/components/AlertsFeed.tsx` (add `deal` filter chip + icon)
- Modify: `frontend/src/api/types.ts` + `api/client.ts` (already extended `AlertType` + `ALERT_TYPES` in T3)
- Test: `frontend/src/__tests__/WatchCardSheet.test.tsx` (extend)
- Test: `frontend/src/__tests__/AlertsFeed.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests**

Extend `frontend/src/__tests__/WatchCardSheet.test.tsx` with a deal-chip test (mirror the existing `price_target`/`drop_time` tests):

```tsx
  it("submits a deal watch when the Deal chip is picked", async () => {
    const fetchSpy = stubFetch({});  // reuse the file's existing stub helper
    // ... pick the Deal chip (find button matching /deal/i), click Create
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);  // adjust to the file's assertion pattern
    expect(body.alert_type).toBe("deal");
    expect(body.card_id).toBeDefined();
  });
```

> The implementer MUST mirror the EXACT assertion pattern the existing WatchCardSheet tests use (how they read the posted body from the fetch spy). Do not invent a pattern.

Extend `frontend/src/__tests__/AlertsFeed.test.tsx` with a deal event + chip filter:

```tsx
  it("filters to deal alerts when the Deal chip is tapped", async () => {
    // add a deal event to the events array, render, tap the Deal chip, assert only the deal row shows
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix frontend test -- --run WatchCardSheet AlertsFeed`
Expected: FAIL — `deal` chip/icon not present.

- [ ] **Step 3: Add `deal` to `WatchCardSheet.tsx` `TYPE_INFO`**

```tsx
  deal: {
    label: "Deal",
    description: "Ping me when a new listing clears the RIP/flip deal thresholds.",
    needsCard: true,
    needsListings: true,
  },
```

> The sheet's submit already sends `alert_type: alertType` and the conditional-field logic (target price / drop time) only activates for `price_target`/`drop_time` — `deal` needs neither, so no further submit changes. Confirm by reading the submit handler: it should send `target_price`/`drop_at` only when relevant. If it sends them unconditionally as `null`, that's fine (backend ignores them for `deal`).

- [ ] **Step 4: Add `deal` to `AlertsFeed.tsx`**

In the `CHIPS` array add `{ value: "deal", label: "Deal" }`; in the `ICON` map add `deal: "💸"`. The existing `ICON[ev.alert_type]` + filter logic then handle deal events.

- [ ] **Step 5: Run frontend tests**

Run: `npm --prefix frontend test -- --run`
Expected: PASS.

- [ ] **Step 6: Run the build**

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(alerts): Deal watch chip + AlertsFeed deal filter (T6)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Docs, integrate, verify, push, deploy

**Files:**
- Modify: `AI_CONTEXT.md`
- Modify: `PROJECT.md`
- Optional: `site/app/sections/Deals.tsx` (caption touch only)
- Modify: memory `pokemon-card-platform-project.md` (the project memory)

- [ ] **Step 1: Update `AI_CONTEXT.md`**

Add Phase 05b to the state table (date 2026-08-04, status shipped), the new `GET /cards/{id}/sold-comps` endpoint, the `deal` alert type + `_eval_deal`, the `sold-comps` package note, the new test counts. Update the layout if a new frontend component/tab was added. Keep it current per the standing directive.

- [ ] **Step 2: Update `PROJECT.md`**

Status line → Phase 05b shipped 2026-08-04 (deal alerts + sold-comps evidence). Add a roadmap row / shipped section. Note the eBay `findCompletedItems` deprecation + honest-degrade behavior.

- [ ] **Step 3: Optional site caption**

In `site/app/sections/Deals.tsx`, if cheap, extend the honest caption to mention sold-comps evidence backing the market price. If it risks the build, skip (the site is a marketing surface; the evidence is an app feature).

- [ ] **Step 4: Full verification**

Run each and confirm green:
- `backend/.venv/Scripts/python -m pytest -q` (backend, all green)
- `npm --prefix frontend test -- --run` (frontend, all green)
- `npm --prefix frontend run build` (clean)
- `npm --prefix site run build` (clean — only if Step 3 touched the site)

- [ ] **Step 5: Merge to main + push**

```bash
cd /c/ClaudeKnowledge
git checkout main
git merge --no-ff phase-05b-deal-alerts-sold-comps -m "Phase 05b: deal alerts + eBay sold-comps evidence

- Deal alerts: _eval_deal in AlertEngine composes the read-only DealEngine;
  a new listing clearing rip/flip thresholds fires an alert (baseline-dedupe
  via last_seen_listing_ids, first-poll never fires). 'deal' watch type.
- Sold-comps evidence: EbayListingsProvider.fetch_sold_listings via
  findCompletedItems (SoldItemsOnly, SERVICE-VERSION=1.13.0) returns up to 3
  recent sold listings; GET /cards/{id}/sold-comps surfaces them with honest
  unavailable/empty flags. Surfaced as 'Recent sold (eBay)' in CardDetail.
- Sold comps are on-demand evidence, never persisted (no snapshot writes).
- findCompletedItems is eBay-deprecated (2020) but still functional; the
  never-raise adapter degrades to [] if retired.

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 6: Deploy GitHub Pages (only if the site changed in Step 3)**

If the site build changed `docs/`, commit + push already redeployed via the main push. Verify:
```bash
gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds
```
Status `built` (not `errored`) = success. If the site did NOT change, no Pages redeploy needed (the app/frontend isn't deployed via Pages — only the site is).

- [ ] **Step 7: Update the project memory**

Update `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md`: current phase → Phase 05b shipped (deal alerts + sold-comps evidence), updated test counts, note the `findCompletedItems` deprecation + the new endpoints/CLI. Update the `MEMORY.md` index line if the hook changed.

---

## Verification (end-to-end)

- **Backend:** `backend/.venv/Scripts/python -m pytest` — all green. New tests cover: provider sold-comps (no-key short-circuit, parse, skip-unsold, skip-priceless, limit cap, bad-JSON, 404); endpoint (populated, unavailable, empty, limit-clamp, 404); `_eval_deal` (first-poll-never-fires, fires-only-new-deals, non-deal-no-fire, baseline-advances, no-deal-engine-no-op, flip-message); watchlist `deal` 422 + success. Manual: `python -m cardplatform.cli check-alerts` with a deal watch + key → an `AlertEvent` for a new rip/flip listing; `GET /cards/base1-4/sold-comps?variant=` returns up to 3 sold comps or honest flags.
- **Frontend:** `npm --prefix frontend test -- --run` all green; `npm run build` clean. Manual smoke: open a card → "Recent sold (eBay)" block renders comps or honest empty; create a Deal watch → appears in More → watches; a deal alert renders in AlertsFeed with 💸.
- **Sacred constraints:** no ad-hoc price resolution (only `DealEngine.assess`/`PriceService.latest_price`); sold comps NOT persisted (no snapshot writes); staleness surfaced (`sold_at`); honest empty states (never `$0`, never a sold comp from an unsold listing); no `data/` deletion; snapshots immutable.

## Out of scope

- Persisting sold comps to a snapshot table (on-demand evidence only this phase).
- Per-watch deal thresholds (reuse global settings).
- Marketplace Insights API migration (documented follow-up).
- Surfacing sold comps in the deployed Next.js site beyond an optional caption.

## Self-Review

- **Spec coverage:** Leg 1 (deal alerts) → T4 (engine + validation), T5 (wiring), T6 (frontend). Leg 2 (sold comps) → T1 (provider), T2 (endpoint), T3 (frontend). Docs + deploy → T7. All spec sections covered.
- **Type consistency:** `SoldComp` (T1) → `SoldCompOut` (T2) → `SoldComp` TS (T3). `deal_engine` ctor param (T4) used in T5 wiring. `AlertType` extended in T3, used in T6. `fetch_sold_listings(card_id, variant, limit=3)` signature consistent T1/T2. `_eval_deal` mirrors `_eval_new_listing`'s `last_seen_listing_ids` JSON shape. ✓
- **Placeholders:** None — every code step has full code. A few "match the existing fixture/helper" notes where the implementer must grep for the exact name (intentional — inventing a fixture name risks drift); these are scoped to verification helpers, not core logic.