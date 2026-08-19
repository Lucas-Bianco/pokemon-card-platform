"""EbayListingsProvider — raw eBay listing search via the Finding API.

Mirrors PkmnPricesProvider's error/retry discipline line-for-line: the fetch
method NEVER raises — every failure mode degrades to [].

Degrade-to-[] philosophy (mirrors PkmnPricesProvider / PokemonTcgIoProvider):
  * No listings_api_key configured -> return [] WITHOUT making a request. This
    is the default state; listings are opt-in, never a crash.
  * 404 / 401 (terminal) -> one attempt, then []. A 404 commonly means eBay has
    no matching listings for the query.
  * Transport error / 5xx / 429 -> retry with exponential backoff, then [].
  * Unparseable JSON or unexpected shape -> [].
  * NEVER raises out of fetch_listings.

eBay search caveat (documented follow-up, NOT solved here):
  eBay Finding API search is keyword-based. We build the query from the card's
  name + number (NO set name — eBay keyword search over-matches on set names)
  when a `catalog_lookup` callable is wired in, else from the raw card_id slug
  (e.g. "base1-4", which returns noisy or empty results). Keyword search may
  surface near-miss listings, so every quote carries `source` + `url` so the
  user can verify each listing in the UI. Tighter id-mapping (e.g. filtering by
  eBay product id, or a card-id -> eBay-product-id mapping) is a documented
  follow-up; until it exists, treat listings as "best-effort keyword matches",
  not authoritative. Do NOT build the mapping here — T1 is listings *fetch*
  only.

Auth: the eBay Finding API takes a single SECURITY-APPNAME (App ID) as a
QUERY PARAM — no OAuth. Lucas's free eBay developer App ID works directly,
sent in `params["SECURITY-APPNAME"]` (not an Authorization header). The 3c
adapter used the Browse API (item_summary/search), which needs a real OAuth
client-credentials token, so it faked a static bearer token and never
returned listings. The Finding API has no such requirement.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from datetime import datetime, timezone

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.listings_provider import ListingQuote, SoldComp
from cardplatform.sealed.provider import SealedListing, SealedSoldComp

logger = logging.getLogger(__name__)


class _TerminalHttpError(Exception):
    """A 4xx (other than 429) — retrying identical requests will never succeed."""


# Type of the optional catalog lookup callable: card_id -> (set_name, number,
# card_name) | None. Kept as a Protocol for readability; providers stay
# decoupled from a DB session.
class _CatalogLookup(Protocol):
    def __call__(self, card_id: str) -> tuple[str, str, str] | None: ...


class EbayListingsProvider:
    name = "ebay"

    def __init__(
        self,
        settings: Settings | None = None,
        catalog: _CatalogLookup | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.catalog = catalog

    def fetch_listings(self, card_id: str, variant: str) -> list[ListingQuote]:
        # No key configured is the default state: listings are opt-in. Return []
        # WITHOUT touching the network — never crash, never raise.
        if not self.settings.listings_api_key:
            return []

        query = self._build_query(card_id)
        payload = self._search(query)
        if payload is None:
            return []

        try:
            return self._parse(card_id, variant, payload)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            # Unexpected JSON shape is an honest "unavailable", not a crash.
            logger.warning("ebay listings parse failure for %s: %s", card_id, exc)
            return []

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
        # endTime is the auction close; for fixed-price listings it is not an auction end,
        # so ignore it (never synthesize an auction_end_at).
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


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an eBay ISO-8601 timestamp to a tz-aware UTC datetime, or None.

    eBay's itemEndDate looks like "2026-08-15T18:30:00.000Z". Python 3.11+
    datetime.fromisoformat accepts "Z" but not the trailing milliseconds in all
    builds; normalize defensively.
    """
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)