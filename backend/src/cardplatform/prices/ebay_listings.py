"""EbayListingsProvider — raw eBay listing search via the Browse API.

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
  eBay Browse API search is keyword-based. We build the query from the card's
  name + set name + number when a `catalog_lookup` callable is wired in, else
  from the raw card_id slug (e.g. "base1-4"). Keyword search may surface
  near-miss listings, so every quote carries `source` + `url` so the user can
  verify each listing in the UI. Tighter id-mapping (e.g. filtering by eBay
  product id, or a card-id -> eBay-product-id mapping) is a documented
  follow-up; until it exists, treat listings as "best-effort keyword matches",
  not authoritative. Do NOT build the mapping here — T2 is listings *fetch*
  only.

Auth caveat (documented follow-up, NOT solved here):
  The eBay Browse API needs an OAuth2 user-token (or the Client Credentials
  grant for guest-restricted calls). For this single-user local-first app we
  treat `listings_api_key` as a bearer/App-Key token and send it via the
  `Authorization: Bearer {token}` header (also accepted as
  `X-EBAY-API-IAF-TOKEN` for the legacy App-Key flow). A real OAuth
  client-credentials flow (token exchange + refresh) is a documented
  follow-up; for now the key is treated as a static bearer token — mirror the
  "document the auth caveat" honesty of PkmnPricesProvider. Do NOT build the
  OAuth flow here.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol
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
from cardplatform.prices.listings_provider import ListingQuote

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
        catalog: Callable[[str], tuple[str, str, str] | None] | None = None,
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

    def _build_query(self, card_id: str) -> str:
        """Build the eBay search query. Use the catalog callable when wired in
        (set_name + number + card_name); else fall back to the raw card_id slug.
        Keyword search is best-effort — see the search caveat in the docstring."""
        if self.catalog is not None:
            try:
                meta = self.catalog(card_id)
            except Exception as exc:  # noqa: BLE001 — catalog is app-supplied
                logger.warning("ebay catalog lookup failed for %s: %s", card_id, exc)
                meta = None
            if meta is not None:
                set_name, number, card_name = meta
                return f"{card_name} {set_name} {number}".strip()
        return card_id

    def _search(self, query: str) -> dict[str, Any] | None:
        """GET the eBay Browse search endpoint, retrying transport/5xx/429 only.

        Mirrors PkmnPricesProvider._get_listings exactly: 404/401 raise
        _TerminalHttpError (one attempt only); 5xx/429/transport return None and
        tenacity retries until the attempt budget is exhausted, then we degrade
        to []. 200-with-bad-JSON raises _TerminalHttpError (terminal, one
        attempt) so tenacity does not burn the budget on identical failures.
        """
        headers = {
            "Authorization": f"Bearer {self.settings.listings_api_key}",
            "X-EBAY-API-IAF-TOKEN": self.settings.listings_api_key,
        }
        url = f"{self.settings.listings_base_url}/item_summary/search"
        params = {"q": query}

        @retry(
            stop=stop_after_attempt(self.settings.http_max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_result(lambda r: r is None),
        )
        def _attempt() -> dict[str, Any] | None:
            try:
                response = httpx.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.settings.http_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                logger.warning("ebay listings transport error for %r: %s", query, exc)
                return None
            if response.status_code == 200:
                try:
                    return response.json()
                except (httpx.DecodingError, ValueError) as exc:
                    # 200 with a non-JSON body will never decode on retry —
                    # terminal, not retryable. Raise _TerminalHttpError so
                    # tenacity stops after one attempt instead of burning the
                    # budget on identical failures; the outer except degrades
                    # to [].
                    logger.warning("ebay listings bad JSON for %r: %s", query, exc)
                    raise _TerminalHttpError(response.status_code) from exc
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "ebay listings HTTP %s for %r (retryable)",
                    response.status_code,
                    query,
                )
                return None
            logger.warning(
                "ebay listings HTTP %s for %r (terminal, not retrying)",
                response.status_code,
                query,
            )
            raise _TerminalHttpError(response.status_code)

        try:
            return _attempt()
        except _TerminalHttpError:
            return None
        except RetryError:
            logger.error(
                "ebay listings gave up for %r after %s attempts",
                query,
                self.settings.http_max_attempts,
            )
            return None

    @staticmethod
    def _parse(
        card_id: str, variant: str, payload: dict[str, Any]
    ) -> list[ListingQuote]:
        """Map eBay `itemSummaries` -> ListingQuotes.

        For each item: listing_id from itemId (or id), price/currency from
        price.value/price.currency (skip if price present but unparseable),
        url from itemWebUrl, title, listing_type from buyingOptions
        (contains "BIDDING" -> "auction", else "fixed_price"), auction_end_at
        from itemEndDate parsed ISO -> tz-aware UTC (or None), condition from
        the condition field (string; None if absent). source="ebay".
        source_updated_at is None: eBay Browse search does not reliably expose
        a per-listing updated stamp; the service normalizes None -> "" for the
        dedupe unique key (mirrors graded_service). Skip rows missing
        listing_id — never fabricate.
        """
        items = payload.get("itemSummaries")
        if not isinstance(items, list):
            return []

        quotes: list[ListingQuote] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            listing_id = item.get("itemId") or item.get("id")
            if not listing_id:
                continue

            price: float | None = None
            currency: str | None = None
            price_block = item.get("price")
            if isinstance(price_block, dict):
                currency = price_block.get("currency")
                raw_value = price_block.get("value")
                if raw_value is not None:
                    try:
                        price = float(raw_value)
                    except (TypeError, ValueError):
                        # Price present but unparseable — skip this listing
                        # rather than fabricate a price.
                        continue

            buying_options = item.get("buyingOptions")
            if isinstance(buying_options, list) and "BIDDING" in buying_options:
                listing_type = "auction"
            else:
                listing_type = "fixed_price"

            auction_end_at = _parse_iso(item.get("itemEndDate"))

            quotes.append(
                ListingQuote(
                    card_id=card_id,
                    variant=variant,
                    listing_id=str(listing_id),
                    title=item.get("title"),
                    price=price,
                    currency=currency,
                    listing_type=listing_type,
                    auction_end_at=auction_end_at,
                    url=item.get("itemWebUrl"),
                    condition=item.get("condition"),
                    source="ebay",
                    source_updated_at=None,
                )
            )
        return quotes


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