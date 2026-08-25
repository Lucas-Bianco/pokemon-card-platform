"""HTTP boundary tests for the shareable binder (roadmap row 21).

Pins the wire contract: GET /binder is read-only and honest (proven_sale null
never $0; unavailable vs empty flags); POST /binder/items is 201 / 404 / 409;
PATCH note updates + clears + 404; DELETE is 204 then 404; POST /binder/reorder
re-orders; GET /binder/export is text/html. Mirrors test_tradeup_api.py: direct
inserts + a dependency override for get_session, with the route's
EbayListingsProvider(catalog=...) construction monkeypatched to a stub.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet
from cardplatform.prices.listings_provider import SoldComp
from datetime import datetime, timezone


class StubEbayProvider:
    """Stands in for EbayListingsProvider at the route's construction site. The
    route builds `EbayListingsProvider(catalog=_catalog_lookup(session))` —
    patching the symbol on the api module swaps that call to this stub."""

    def __init__(self, comps_by_key, *args, **kwargs):
        self.comps_by_key = comps_by_key

    def fetch_sold_listings(self, card_id, variant, limit=3):
        return list(self.comps_by_key.get((card_id, variant), []))[:limit]


def _comp(price: float, card_id="base1-4", variant="normal"):
    return SoldComp(
        card_id=card_id,
        variant=variant,
        listing_id=f"l{price}",
        price=price,
        title="Charizard",
        currency="USD",
        sold_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        condition="Raw",
    )


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(CardSet(id="base2", name="Jungle", series="Jungle"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", rarity="Rare Holo"))
    db.add(Card(id="base2-1", set_id="base2", name="Pikachu", number="1", rarity="Common"))
    db.commit()
    return db


@pytest.fixture
def client(seeded, monkeypatch):
    """A client whose route uses a stub EbayListingsProvider with a proven sale
    for (base1-4, normal) and none for (base2-1, normal). Key is 'set'."""
    comps = {("base1-4", "normal"): [_comp(118.0)]}
    import cardplatform.api as api_module
    monkeypatch.setattr(
        api_module,
        "EbayListingsProvider",
        lambda *a, **kw: StubEbayProvider(comps, *a, **kw),
    )
    # Force listings_api_key_set=True so 'no comps' reads as empty, not unavailable.
    monkeypatch.setattr(api_module.settings, "listings_api_key", "stub-key", raising=False)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


@pytest.fixture
def keyless_client(seeded, monkeypatch):
    """A keyless server (no listings_api_key) — proven reads are 'unavailable'."""
    import cardplatform.api as api_module
    monkeypatch.setattr(
        api_module,
        "EbayListingsProvider",
        lambda *a, **kw: StubEbayProvider({}, *a, **kw),
    )
    monkeypatch.setattr(api_module.settings, "listings_api_key", None, raising=False)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def test_get_binder_empty(client):
    r = client.get("/binder")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_add_item_returns_joined_slot_with_proven_sale(client):
    r = client.post("/binder/items", json={"card_id": "base1-4"})
    assert r.status_code == 201
    body = r.json()
    assert body["card_id"] == "base1-4"
    assert body["card_name"] == "Charizard"
    assert body["set_name"] == "Base"
    assert body["rarity"] == "Rare Holo"
    # Proven sale attached, never a fabricated $0.
    assert body["proven_sale"] is not None
    assert body["proven_sale"]["price"] == 118.0
    assert body["proven_sale_unavailable"] is False
    assert body["proven_sale_empty"] is False
    # sort_order starts at 1.
    assert body["sort_order"] == 1


def test_add_item_unknown_card_404(client):
    r = client.post("/binder/items", json={"card_id": "nope-1"})
    assert r.status_code == 404


def test_add_item_duplicate_409(client):
    client.post("/binder/items", json={"card_id": "base1-4"})
    r = client.post("/binder/items", json={"card_id": "base1-4"})
    assert r.status_code == 409


def test_add_item_with_note_persists(client):
    r = client.post("/binder/items", json={"card_id": "base1-4", "note": "grail"})
    assert r.status_code == 201
    assert r.json()["note"] == "grail"


def test_set_note_updates_and_clears(client):
    client.post("/binder/items", json={"card_id": "base1-4"})
    r = client.patch("/binder/items/base1-4/normal", json={"note": "top tier"})
    assert r.status_code == 200
    assert r.json()["note"] == "top tier"
    # Clear with null.
    r = client.patch("/binder/items/base1-4/normal", json={"note": None})
    assert r.status_code == 200
    assert r.json()["note"] is None


def test_set_note_unknown_slot_404(client):
    r = client.patch("/binder/items/base2-1/normal", json={"note": "x"})
    assert r.status_code == 404


def test_delete_item_204_then_404(client):
    client.post("/binder/items", json={"card_id": "base1-4"})
    r = client.delete("/binder/items/base1-4/normal")
    assert r.status_code == 204
    r = client.delete("/binder/items/base1-4/normal")
    assert r.status_code == 404


def test_list_binder_orders_and_marks_empty_vs_unavailable(client):
    client.post("/binder/items", json={"card_id": "base2-1"})  # no comps
    client.post("/binder/items", json={"card_id": "base1-4"})  # has comps
    r = client.get("/binder")
    items = r.json()["items"]
    assert [i["card_id"] for i in items] == ["base2-1", "base1-4"]
    # base2-1: key set, no comps -> empty (proven_sale null, never $0).
    assert items[0]["proven_sale"] is None
    assert items[0]["proven_sale_unavailable"] is False
    assert items[0]["proven_sale_empty"] is True
    # base1-4: has proven sale.
    assert items[1]["proven_sale"]["price"] == 118.0


def test_list_binder_keyless_marks_unavailable(keyless_client):
    keyless_client.post("/binder/items", json={"card_id": "base1-4"})
    r = keyless_client.get("/binder")
    item = r.json()["items"][0]
    # No key -> unavailable (so UI says "set a key"), proven_sale null, never $0.
    assert item["proven_sale"] is None
    assert item["proven_sale_unavailable"] is True
    assert item["proven_sale_empty"] is False


def test_reorder_changes_list_order(client):
    client.post("/binder/items", json={"card_id": "base1-4"})
    client.post("/binder/items", json={"card_id": "base2-1"})
    r = client.post(
        "/binder/reorder",
        json={"items": [{"card_id": "base2-1"}, {"card_id": "base1-4"}]},
    )
    assert r.status_code == 204
    items = client.get("/binder").json()["items"]
    assert [i["card_id"] for i in items] == ["base2-1", "base1-4"]


def test_export_binder_is_text_html_and_honest(client):
    client.post("/binder/items", json={"card_id": "base1-4", "note": "grail"})
    client.post("/binder/items", json={"card_id": "base2-1"})  # no comps
    r = client.get("/binder/export")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    doc = r.text
    assert "<style>" in doc  # self-contained
    assert "Charizard" in doc
    assert "Pikachu" in doc
    assert "118" in doc  # proven price baked in
    assert "no proven sale yet" in doc.lower()  # honest empty
    assert "grail" in doc  # note rendered