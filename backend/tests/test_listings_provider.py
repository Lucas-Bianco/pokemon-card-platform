"""T2: EbayListingsProvider — listing parsing + degrade-to-[] guarantees.

Mirrors test_pkmnprices_provider.py's respx-mocked-httpx pattern. No real
network: every request is mocked via respx. The provider must NEVER raise —
every failure mode (no key, 404, transport error, 5xx after retries, bad JSON,
unexpected shape) degrades to [].
"""

from __future__ import annotations

import httpx
import respx

from cardplatform.config import Settings
from cardplatform.prices.listings_provider import ListingQuote
from cardplatform.prices.ebay_listings import EbayListingsProvider

# eBay Browse API item_summary/search shape per
# https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
SEARCH_RESPONSE = {
    "itemSummaries": [
        {
            "itemId": "v1|123456789|0",
            "title": "Charizard Base 4 PSA 10",
            "price": {"value": "275.00", "currency": "USD"},
            "itemWebUrl": "https://www.ebay.com/itm/123456789",
            "buyingOptions": ["FIXED_PRICE", "BUY_IT_NOW"],
            "condition": "Used",
        },
        {
            "itemId": "v1|987654321|0",
            "title": "Charizard auction",
            "price": {"value": "50.00", "currency": "USD"},
            "itemWebUrl": "https://www.ebay.com/itm/987654321",
            "buyingOptions": ["BIDDING"],
            "itemEndDate": "2026-08-15T18:30:00.000Z",
        },
    ],
}


def _route():
    """Match the eBay search endpoint regardless of the query string."""
    return respx.route(
        method="GET",
        url__startswith="https://api.ebay.com/buy/browse/v1/item_summary/search",
    )


def test_no_key_returns_empty_no_network(monkeypatch):
    """Default state: no listings_api_key configured. Provider must NOT call httpx."""
    settings = Settings(listings_api_key=None)

    called = {"count": 0}

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        called["count"] += 1
        raise AssertionError("httpx.get must not be called when no API key is set")

    monkeypatch.setattr(httpx, "get", _fail_if_called)

    quotes = EbayListingsProvider(settings).fetch_listings("base1-4", "normal")

    assert quotes == []
    assert called["count"] == 0


@respx.mock
def test_parses_fixed_price_and_auction():
    settings = Settings(listings_api_key="ebay-token")
    _route().mock(return_value=httpx.Response(200, json=SEARCH_RESPONSE))

    quotes = EbayListingsProvider(settings).fetch_listings("base1-4", "normal")

    assert len(quotes) == 2
    by_id = {q.listing_id: q for q in quotes}

    fixed = by_id["v1|123456789|0"]
    assert fixed.listing_type == "fixed_price"
    assert fixed.price == 275.0
    assert fixed.currency == "USD"
    assert fixed.url == "https://www.ebay.com/itm/123456789"
    assert fixed.title == "Charizard Base 4 PSA 10"
    assert fixed.condition == "Used"
    assert fixed.source == "ebay"
    assert fixed.auction_end_at is None
    assert isinstance(fixed, ListingQuote)

    auction = by_id["v1|987654321|0"]
    assert auction.listing_type == "auction"
    assert auction.price == 50.0
    assert auction.auction_end_at is not None
    assert auction.auction_end_at.tzinfo is not None  # tz-aware
    assert auction.auction_end_at.year == 2026
    assert auction.auction_end_at.month == 8
    assert auction.auction_end_at.day == 15


@respx.mock
def test_bad_json_terminal_no_retry():
    """200 with a non-JSON body will never decode on retry — terminal, so it must
    stop after ONE attempt, not burn the retry budget on identical failures."""
    settings = Settings(listings_api_key="ebay-token", http_max_attempts=5)
    route = _route()
    route.mock(
        return_value=httpx.Response(
            200,
            content=b"<html>not json</html>",
            headers={"content-type": "text/html"},
        )
    )

    assert EbayListingsProvider(settings).fetch_listings("base1-4", "normal") == []
    assert route.call_count == 1


@respx.mock
def test_404_terminal():
    """A 404 is terminal — one attempt, then []."""
    settings = Settings(listings_api_key="ebay-token", http_max_attempts=5)
    route = _route()
    route.mock(return_value=httpx.Response(404))

    assert EbayListingsProvider(settings).fetch_listings("base1-4", "normal") == []
    assert route.call_count == 1


@respx.mock
def test_5xx_retries_then_empty():
    """5xx is retryable; after the budget is exhausted it degrades to []."""
    settings = Settings(listings_api_key="ebay-token", http_max_attempts=3)
    route = _route()
    route.mock(return_value=httpx.Response(503))

    assert EbayListingsProvider(settings).fetch_listings("base1-4", "normal") == []
    assert route.call_count == 3


@respx.mock
def test_parse_failure_returns_empty():
    """A 200 with an unexpected shape (itemSummaries not a list) is honest [],
    not a crash."""
    settings = Settings(listings_api_key="ebay-token")
    _route().mock(
        return_value=httpx.Response(200, json={"itemSummaries": "not a list"})
    )

    assert EbayListingsProvider(settings).fetch_listings("base1-4", "normal") == []


@respx.mock
def test_never_raises(monkeypatch):
    """A transport-level error is retryable; after retries it degrades to [],
    never raises out of fetch_listings."""
    settings = Settings(listings_api_key="ebay-token", http_max_attempts=2)

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)

    assert EbayListingsProvider(settings).fetch_listings("base1-4", "normal") == []


@respx.mock
def test_parse_skips_items_missing_listing_id():
    """Items without an itemId/id are skipped — never fabricated."""
    settings = Settings(listings_api_key="ebay-token")
    _route().mock(
        return_value=httpx.Response(
            200,
            json={
                "itemSummaries": [
                    {"itemId": "v1|1|0", "title": "ok", "price": {"value": "10.00", "currency": "USD"}},
                    {"title": "no id here", "price": {"value": "20.00", "currency": "USD"}},
                ]
            },
        )
    )

    quotes = EbayListingsProvider(settings).fetch_listings("base1-4", "normal")
    assert len(quotes) == 1
    assert quotes[0].listing_id == "v1|1|0"