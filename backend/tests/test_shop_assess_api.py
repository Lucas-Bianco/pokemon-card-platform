"""Phase E: GET /shop/assess?url=&limit= — assess a single eBay listing by URL.

Mirrors test_card_lookup_api.py's get_session override (the route builds its own
ShopAssessor(session, settings, provider)) + test_sealed_sold_comps_api.py's
`cardplatform.api.settings` monkeypatch + EbayListingsProvider method stubs, so no
network and no real DB is touched. Honest flags: no key -> listing_unavailable; key
set, not found -> listing_not_found; no match -> deal None; non-ebay URL -> 422.
Composes the deal-sniper market (sold-comps median) + Phase 07 authenticity, all
read-only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import SealedProduct
from cardplatform.prices import ebay_listings as ebay_mod
from cardplatform.sealed.provider import SealedListing, SealedSoldComp

EBAY_URL = "https://www.ebay.com/itm/123456789012"


def _listing(title="Scarlet & Violet Elite Trainer Box Sealed", price=15.0):
    return SealedListing(
        query="",
        listing_id="123",
        source="ebay",
        title=title,
        price=price,
        currency="USD",
        listing_type="fixed_price",
        auction_end_at=None,
        url="https://www.ebay.com/itm/123",
        condition="New",
        source_updated_at=None,
        seller="cardseller",
        image_url="https://img.example/x.jpg",
    )


def _comp(price):
    return SealedSoldComp(
        query="etb",
        listing_id=f"c{price}",
        price=price,
        currency="USD",
        title="ETB",
        url="https://ebay.example/c",
        condition="New",
        source="ebay",
    )


@pytest.fixture
def shop_client(db, monkeypatch, tmp_path):
    """Factory: install settings + provider stubs + get_session override, return a
    TestClient. Caller picks key/listing/comps per case."""
    def make(*, key="an-app-id", listing=None, comps=None, seed_catalog=False):
        monkeypatch.setattr(
            "cardplatform.api.settings",
            Settings(data_dir=tmp_path, listings_api_key=key),
        )
        monkeypatch.setattr(
            ebay_mod.EbayListingsProvider,
            "fetch_listing_by_id",
            lambda self, item_id: listing,
        )
        monkeypatch.setattr(
            ebay_mod.EbayListingsProvider,
            "fetch_sold_listings_by_query",
            lambda self, query, limit=6: comps or [],
        )
        if seed_catalog:
            db.add(
                SealedProduct(
                    slug="sv-etb",
                    name="Scarlet & Violet Elite Trainer Box",
                    product_type="etb",
                )
            )
            db.commit()
        app.dependency_overrides[get_session] = lambda: db
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_shop_assess_422_non_ebay_url(shop_client):
    """A URL that is not an eBay /itm/<id> listing is a 422, not a 5xx."""
    client = shop_client()
    r = client.get("/shop/assess", params={"url": "https://example.com/xyz"})
    assert r.status_code == 422


def test_shop_assess_limit_out_of_range_422(shop_client):
    client = shop_client()
    assert client.get("/shop/assess", params={"url": EBAY_URL, "limit": 0}).status_code == 422
    assert client.get("/shop/assess", params={"url": EBAY_URL, "limit": 11}).status_code == 422


def test_shop_assess_unavailable_when_no_key(shop_client):
    """No listings key -> listing_unavailable (honest), listing None, deal None."""
    client = shop_client(key=None)
    r = client.get("/shop/assess", params={"url": EBAY_URL})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == EBAY_URL
    assert body["item_id"] == "123456789012"
    assert body["listing_unavailable"] is True
    assert body["listing"] is None
    assert body["deal"] is None
    assert body["match"]["kind"] == "none"
    assert body["authenticity"] is None
    assert body["caveat"]  # never empty


def test_shop_assess_not_found_when_key_set_but_no_listing(shop_client):
    """Key set but the fetch returns None -> listing_not_found (honest), not a 5xx."""
    client = shop_client(key="an-app-id", listing=None)
    r = client.get("/shop/assess", params={"url": EBAY_URL})
    assert r.status_code == 200
    body = r.json()
    assert body["listing_unavailable"] is False
    assert body["listing_not_found"] is True
    assert body["listing"] is None
    assert body["deal"] is None


def test_shop_assess_no_match_shows_listing_facts_only(shop_client):
    """A listing whose title matches nothing in the catalog -> listing facts + match
    none + deal None, never a fabricated market."""
    client = shop_client(
        key="an-app-id",
        listing=_listing(title="gibberish xyz nothing matches this"),
        comps=[],
    )
    r = client.get("/shop/assess", params={"url": EBAY_URL})
    assert r.status_code == 200
    body = r.json()
    assert body["listing_unavailable"] is False
    assert body["listing_not_found"] is False
    assert body["listing"]["item_id"] == "123456789012"
    assert body["listing"]["title"] == "gibberish xyz nothing matches this"
    assert body["listing"]["price"] == 15.0
    assert body["listing"]["seller"] == "cardseller"
    assert body["listing"]["image_url"] == "https://img.example/x.jpg"
    assert body["listing"]["source"] == "ebay"
    assert body["match"]["kind"] == "none"
    assert body["deal"] is None
    assert body["authenticity"] is None


def test_shop_assess_sealed_match_deal(shop_client):
    """A listing whose title matches a seeded sealed product -> sealed match (high
    confidence) + deal verdict against the sold-comps median. Below market +
    over threshold -> is_deal True, proven market_source "ebay"."""
    client = shop_client(
        key="an-app-id",
        listing=_listing(title="Scarlet & Violet Elite Trainer Box Sealed", price=15.0),
        comps=[_comp(38.0), _comp(40.0), _comp(42.0)],
        seed_catalog=True,
    )
    r = client.get("/shop/assess", params={"url": EBAY_URL, "limit": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["match"]["kind"] == "sealed"
    assert body["match"]["confidence"] == "high"
    assert body["match"]["sealed_slug"] == "sv-etb"
    assert body["match"]["sealed_name"] == "Scarlet & Violet Elite Trainer Box"
    deal = body["deal"]
    assert deal is not None
    assert deal["market"] == 40.0  # median of 38/40/42
    assert deal["market_source"] == "ebay"
    assert deal["sold_comps_count"] == 3
    assert deal["edge"] == 25.0  # 40 - 15
    assert deal["is_deal"] is True
    assert deal["market_unavailable"] is False
    assert deal["market_empty"] is False
    # Sealed matches never run the authenticity guide (card-only).
    assert body["authenticity"] is None


def test_shop_assess_sealed_market_empty_is_honest(shop_client):
    """A sealed match with zero sold comps -> market None, edge None, is_deal False,
    market_empty True (never a fabricated $0)."""
    client = shop_client(
        key="an-app-id",
        listing=_listing(title="Scarlet & Violet Elite Trainer Box Sealed", price=15.0),
        comps=[],
        seed_catalog=True,
    )
    r = client.get("/shop/assess", params={"url": EBAY_URL})
    assert r.status_code == 200
    deal = r.json()["deal"]
    assert deal["market"] is None
    assert deal["market_source"] is None
    assert deal["edge"] is None
    assert deal["is_deal"] is False
    assert deal["market_empty"] is True