"""T3: sealed ledger HTTP endpoints — GET/POST/DELETE /sealed/ledger + valuate routes.

Pins the honest-data contract at the boundary:
- GET /sealed/ledger surfaces `listings_unavailable` (no eBay key) instead of fabricated $0.
- POST /sealed/ledger rejects bad input with 422 (client mistake, not a 500).
- DELETE /sealed/ledger/{id} is 404 then 204.
- POST /sealed/ledger/valuate refreshes every purchase and reports the diagnostic flags.
- POST /sealed/ledger/{id}/valuate refreshes one and returns the refreshed entry (404 on
  unknown).

Session override follows the repo idiom established in test_watchlist_api.py:
`app.dependency_overrides[get_session] = lambda: db` (returns the Session directly, not a
generator). Routes are mounted at root (no `/api/` prefix) — matches the rest of the API.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.sealed.ledger import LedgerService
from cardplatform.sealed.provider import SealedSoldComp


def _client(monkeypatch, db, key="app-id"):
    """FastAPI dependency override matching the repo idiom (see test_watchlist_api.py).

    Monkeypatches `cardplatform.api.settings` so the routes see the desired eBay-key state;
    the routes read the module-level `settings` singleton when building the provider + the
    `listings_unavailable` flag.
    """
    app = create_app()
    monkeypatch.setattr(
        "cardplatform.api.settings",
        Settings(listings_api_key=key, sealed_sold_comp_limit=10),
    )
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def _comp(price, listing_id="c1"):
    return SealedSoldComp(query="box", listing_id=listing_id, price=price)


def _stub_provider(monkeypatch, comps=None):
    comps = comps if comps is not None else [_comp(60.0), _comp(64.0), _comp(70.0)]

    class _P:
        name = "fake"

        def fetch_listings_by_query(self, query):
            return []

        def fetch_sold_listings_by_query(self, query, limit=3):
            return list(comps)

    monkeypatch.setattr(
        "cardplatform.prices.ebay_listings.EbayListingsProvider.fetch_sold_listings_by_query",
        _P().fetch_sold_listings_by_query,
    )


def test_get_ledger_empty_when_no_purchases(db, monkeypatch):
    client = _client(monkeypatch, db)
    r = client.get("/sealed/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["purchases"] == []
    assert body["listings_unavailable"] is False  # key is set in _client


def test_get_ledger_listings_unavailable_when_no_key(db, monkeypatch):
    client = _client(monkeypatch, db, key=None)
    r = client.get("/sealed/ledger")
    assert r.status_code == 200
    assert r.json()["listings_unavailable"] is True


def test_post_ledger_creates_purchase(db, monkeypatch):
    client = _client(monkeypatch, db)
    r = client.post(
        "/sealed/ledger",
        json={"query": "scarlet violet booster box", "quantity": 2, "cost_per_unit": 120.0},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["quantity"] == 2
    assert body["query"] == "scarlet violet booster box"


def test_post_ledger_rejects_bad_input(db, monkeypatch):
    client = _client(monkeypatch, db)
    assert client.post("/sealed/ledger", json={"query": "", "cost_per_unit": 10.0}).status_code == 422
    assert client.post("/sealed/ledger", json={"query": "x", "quantity": 0, "cost_per_unit": 10.0}).status_code == 422
    assert client.post("/sealed/ledger", json={"query": "x", "cost_per_unit": -5.0}).status_code == 422


def test_delete_ledger_404_then_204(db, monkeypatch):
    client = _client(monkeypatch, db)
    assert client.delete("/sealed/ledger/999").status_code == 404
    pid = client.post("/sealed/ledger", json={"query": "box", "cost_per_unit": 10.0}).json()["id"]
    assert client.delete(f"/sealed/ledger/{pid}").status_code == 204


def test_valuate_all_refreshes_and_returns_result(db, monkeypatch):
    _stub_provider(monkeypatch)
    client = _client(monkeypatch, db)
    client.post("/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0})
    r = client.post("/sealed/ledger/valuate")
    assert r.status_code == 200
    body = r.json()
    assert body["valued"] == 1
    assert body["skipped_no_comps"] == 0
    assert body["skipped_no_key"] is False
    entries = client.get("/sealed/ledger").json()["purchases"]
    assert entries[0]["valued"] is True
    assert entries[0]["value_per_unit"] == 64.0  # median of [60,64,70]
    assert entries[0]["profit"] is not None


def test_valuate_all_no_key_skips(db, monkeypatch):
    _stub_provider(monkeypatch, comps=[])
    client = _client(monkeypatch, db, key=None)
    client.post("/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0})
    r = client.post("/sealed/ledger/valuate")
    body = r.json()
    assert body["valued"] == 0
    assert body["skipped_no_key"] is True


def test_valuate_one_returns_refreshed_entry(db, monkeypatch):
    _stub_provider(monkeypatch)
    client = _client(monkeypatch, db)
    pid = client.post("/sealed/ledger", json={"query": "box", "cost_per_unit": 50.0}).json()["id"]
    r = client.post(f"/sealed/ledger/{pid}/valuate")
    assert r.status_code == 200
    body = r.json()
    assert body["valued"] is True
    assert body["value_per_unit"] == 64.0
    assert client.post("/sealed/ledger/999/valuate").status_code == 404