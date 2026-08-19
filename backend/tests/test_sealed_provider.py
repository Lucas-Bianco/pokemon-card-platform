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
    assert listings[1].auction_end_at is None or hasattr(listings[1], "auction_end_at", "tzinfo")


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