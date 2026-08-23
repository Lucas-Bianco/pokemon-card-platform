"""Tests for EbayListingsProvider.fetch_listing_by_id + parse_ebay_item_id (Phase E).

Single-listing fetch via the Finding API getSingleItem operation (same SECURITY-APPNAME
query-param auth, no OAuth, no new key). Same never-raise discipline as the other
operations: no key -> None without a network call; transport/4xx/5xx/parse errors ->
None (degrade, never raise). seller + image_url are pulled separately from the raw
item; core fields come from the shared `_extract_listing_fields`.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from cardplatform.config import Settings
from cardplatform.prices.ebay_listings import EbayListingsProvider, parse_ebay_item_id


def _single_item_response(item, ack="Success"):
    """Build a getSingleItemResponse payload (list-wrapped, as eBay returns)."""
    return {"getSingleItemResponse": [{"item": [item], "ack": [ack]}]}


def _item(
    item_id="123",
    price="118.00",
    currency="USD",
    title="Charizard #4",
    ltype="FixedPrice",
    end="2026-08-30T18:30:00.000Z",
    cond="Used",
    url="https://www.ebay.com/itm/123",
    seller="cardshop",
    picture="https://i.ebayimg.com/images/g/abc.jpg",
):
    return {
        "itemId": [item_id],
        "title": [title],
        "sellingStatus": [
            {
                "currentPrice": [{"@currencyId": currency, "__value__": price}],
            }
        ],
        "listingInfo": [{"listingType": [ltype], "endTime": [end]}],
        "condition": [{"conditionDisplayName": [cond]}],
        "viewItemURL": [url],
        "sellerInfo": [{"sellerUserName": [seller]}],
        "pictureURL": [picture],
    }


# --- parse_ebay_item_id ----------------------------------------------------

def test_parse_item_id_basic():
    assert parse_ebay_item_id("https://www.ebay.com/itm/123456789012") == "123456789012"


def test_parse_item_id_with_query_suffix():
    assert parse_ebay_item_id("https://www.ebay.com/itm/123456789012?hash=abc") == "123456789012"


def test_parse_item_id_de_domain():
    assert parse_ebay_item_id("https://www.ebay.de/itm/99") == "99"


def test_parse_item_id_non_ebay_domain():
    assert parse_ebay_item_id("https://example.com/itm/123") is None


def test_parse_item_id_no_digits():
    assert parse_ebay_item_id("https://www.ebay.com/itm/") is None


def test_parse_item_id_none_and_empty():
    assert parse_ebay_item_id(None) is None
    assert parse_ebay_item_id("") is None


# --- fetch_listing_by_id ---------------------------------------------------

def test_no_key_returns_none_without_network(monkeypatch):
    prov = EbayListingsProvider(settings=Settings())
    mock_get = Mock(side_effect=AssertionError("no network"))
    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get", mock_get)
    assert prov.fetch_listing_by_id("123") is None
    mock_get.assert_not_called()


def test_happy_path_returns_sealed_listing(monkeypatch):
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    payload = _single_item_response(_item())
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get", fake_get)
    listing = prov.fetch_listing_by_id("123")

    assert listing is not None
    assert listing.listing_id == "123"
    assert listing.source == "ebay"
    assert listing.title == "Charizard #4"
    assert listing.price == 118.0
    assert listing.currency == "USD"
    assert listing.url == "https://www.ebay.com/itm/123"
    assert listing.seller == "cardshop"
    assert listing.image_url == "https://i.ebayimg.com/images/g/abc.jpg"
    assert listing.query == ""
    assert listing.source_updated_at is None
    # operation/params sanity
    assert captured["params"]["OPERATION-NAME"] == "getSingleItem"
    assert captured["params"]["SERVICE-VERSION"] == "1.13.0"
    assert captured["params"]["SECURITY-APPNAME"] == "test-key"
    assert captured["params"]["itemId"] == "123"


def test_ack_failure_returns_none(monkeypatch):
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    payload = _single_item_response(_item(), ack="Failure")
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.httpx.get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )
    assert prov.fetch_listing_by_id("123") is None


def test_no_item_returns_none(monkeypatch):
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    payload = {"getSingleItemResponse": [{"ack": ["Success"]}]}  # no item
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.httpx.get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )
    assert prov.fetch_listing_by_id("123") is None


def test_parse_error_degrades_to_none(monkeypatch):
    """Non-JSON / malformed payload -> None, never raises."""
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))

    def fake_get(url, params=None, timeout=None):
        response = SimpleNamespace(status_code=200)
        # .json() raises — simulates malformed body
        response.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
        return response

    monkeypatch.setattr("cardplatform.prices.ebay_listings.httpx.get", fake_get)
    assert prov.fetch_listing_by_id("123") is None


def test_terminal_404_degrades_to_none(monkeypatch):
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.httpx.get",
        lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {}),
    )
    assert prov.fetch_listing_by_id("123") is None


def test_dict_wrapped_response_handled(monkeypatch):
    """Defensively handle a dict-wrapped (not list-wrapped) getSingleItemResponse."""
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    item = _item()
    payload = {
        "getSingleItemResponse": {
            "ack": ["Success"],
            "item": [item],
        }
    }
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.httpx.get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )
    listing = prov.fetch_listing_by_id("123")
    assert listing is not None
    assert listing.listing_id == "123"
    assert listing.seller == "cardshop"


def test_missing_seller_and_image_ok(monkeypatch):
    """seller/image are optional — None when absent, never fabricated."""
    prov = EbayListingsProvider(settings=Settings(listings_api_key="test-key"))
    item = _item()
    del item["sellerInfo"]
    del item["pictureURL"]
    payload = _single_item_response(item)
    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.httpx.get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )
    listing = prov.fetch_listing_by_id("123")
    assert listing is not None
    assert listing.seller is None
    assert listing.image_url is None