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
    assert captured["params"]["SERVICE-VERSION"] == "1.13.0"
    assert captured["params"]["OPERATION-NAME"] == "findCompletedItems"
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