"""T5: listings HTTP endpoint — refresh + return, with honest empty states.

Pins the contract: unknown card 404; no `listings_api_key` configured ->
`listings: []` AND `listings_unavailable: true` (honest — no provider configured,
never fake listings); provider configured but returns listings ->
`listings_unavailable: false`. The provider is monkeypatched so no network is
touched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.prices.ebay_listings import EbayListingsProvider
from cardplatform.prices.listings_provider import ListingQuote


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def test_listings_unknown_card_404(client):
    response = client.post("/cards/bogus-1/listings")
    assert response.status_code == 404
    assert "unknown card" in response.json()["detail"]


def test_listings_unavailable_when_no_key(client):
    """Default settings have no listings_api_key -> honest unavailable flag."""
    response = client.post("/cards/base1-4/listings")
    assert response.status_code == 200
    body = response.json()
    assert body == {"listings": [], "listings_unavailable": True}


def test_listings_returns_when_configured(seeded, tmp_path, monkeypatch):
    """Provider configured (key set) + monkeypatched fetch -> listings populated
    and listings_unavailable False (the source was queried, just not over the
    network)."""
    custom = Settings(data_dir=tmp_path, listings_api_key="test-key")
    monkeypatch.setattr("cardplatform.api.settings", custom)

    canned = [
        ListingQuote(
            card_id="base1-4",
            variant="",
            listing_id="ebay-1",
            title="Charizard",
            price=25.0,
            currency="USD",
            listing_type="fixed_price",
            auction_end_at=None,
            url="https://www.ebay.com/itm/1",
            condition="Used",
            source="ebay",
            source_updated_at=None,
        ),
    ]
    monkeypatch.setattr(
        EbayListingsProvider, "fetch_listings", lambda self, c, v: canned
    )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    client = TestClient(app)

    response = client.post("/cards/base1-4/listings")
    assert response.status_code == 200
    body = response.json()
    assert body["listings_unavailable"] is False
    assert len(body["listings"]) == 1
    listing = body["listings"][0]
    assert listing["listing_id"] == "ebay-1"
    assert listing["price"] == 25.0
    assert listing["source"] == "ebay"
    assert listing["currency"] == "USD"


def test_listings_variant_param_passed_through(seeded, tmp_path, monkeypatch):
    """?variant=holofoil is forwarded to the provider and the service."""
    custom = Settings(data_dir=tmp_path, listings_api_key="test-key")
    monkeypatch.setattr("cardplatform.api.settings", custom)

    seen = {}

    def fake_fetch(self, card_id, variant):
        seen["variant"] = variant
        return []

    monkeypatch.setattr(EbayListingsProvider, "fetch_listings", fake_fetch)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    client = TestClient(app)

    response = client.post("/cards/base1-4/listings", params={"variant": "holofoil"})
    assert response.status_code == 200
    assert seen["variant"] == "holofoil"
    assert response.json()["listings_unavailable"] is False


def test_listings_endpoint_wires_catalog_lookup(seeded, tmp_path, monkeypatch):
    """The endpoint wires the catalog lookup so the eBay keyword is the card's
    name + number (not the raw 'base1-4' slug, which returns nothing on eBay).
    Configures a key (so fetch_listings doesn't short-circuit) and stubs the
    network search to None (no HTTP) while letting the real fetch_listings +
    _build_query run, so the spy captures the keyword.
    """
    custom = Settings(data_dir=tmp_path, listings_api_key="test-key")
    monkeypatch.setattr("cardplatform.api.settings", custom)
    # The provider defaults to the module-level `default_settings` it imported
    # at load time (NOT cardplatform.api.settings), so patch that binding too —
    # otherwise fetch_listings short-circuits on "no key" before _build_query.
    monkeypatch.setattr("cardplatform.prices.ebay_listings.default_settings", custom)

    captured = {}
    orig = EbayListingsProvider._build_query

    def spy(self, card_id):
        q = orig(self, card_id)
        captured["query"] = q
        return q

    monkeypatch.setattr(EbayListingsProvider, "_build_query", spy)
    monkeypatch.setattr(EbayListingsProvider, "_search", lambda self, q: None)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    client = TestClient(app)

    r = client.post("/cards/base1-4/listings", params={"variant": "holofoil"})
    assert r.status_code == 200
    assert captured["query"] != "base1-4"
    assert captured["query"].endswith("4")