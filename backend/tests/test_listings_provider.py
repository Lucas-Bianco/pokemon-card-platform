"""T2: EbayListingsProvider — Finding API parsing + degrade-to-[] guarantees.

The provider must NEVER raise — every failure mode (no key, 404, transport
error, 5xx after retries, bad JSON, unexpected shape) degrades to []. The
Finding API is XML-first; serialized to JSON it wraps every field in a
single-element array, so each access is `[0]`.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from cardplatform.config import Settings
from cardplatform.prices.listings_provider import ListingQuote
from cardplatform.prices.ebay_listings import EbayListingsProvider


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
    assert q.auction_end_at is None  # FixedPrice
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


def test_finding_api_5xx_retries_then_empty():
    """5xx is retryable; after the budget is exhausted it degrades to []."""
    p = EbayListingsProvider(Settings(http_max_attempts=3, listings_api_key="k"))
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 503
        mock_get.return_value.json.return_value = {}
        assert p.fetch_listings("base1-4", "holofoil") == []
    assert mock_get.call_count == 3


def test_transport_error_never_raises():
    """A transport-level error is retryable; after retries it degrades to [],
    never raises out of fetch_listings."""
    p = EbayListingsProvider(Settings(http_max_attempts=2, listings_api_key="k"))
    with patch(
        "cardplatform.prices.ebay_listings.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        assert p.fetch_listings("base1-4", "holofoil") == []


def test_finding_api_item_missing_listing_id_is_skipped():
    """Items without an itemId are skipped — never fabricated."""
    payload = _finding_payload([
        {"itemId": ["1"], "title": ["ok"],
         "sellingStatus": [{"currentPrice": [{"@currencyId": "USD", "__value__": "10.0"}]}],
         "listingInfo": [{"listingType": ["FixedPrice"]}]},
        {"title": ["no id here"],
         "sellingStatus": [{"currentPrice": [{"@currencyId": "USD", "__value__": "20.0"}]}],
         "listingInfo": [{"listingType": ["FixedPrice"]}]},
    ])
    p = EbayListingsProvider(_settings_with_key())
    with patch("cardplatform.prices.ebay_listings.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        quotes = p.fetch_listings("base1-4", "holofoil")
    assert len(quotes) == 1
    assert quotes[0].listing_id == "1"
    assert isinstance(quotes[0], ListingQuote)