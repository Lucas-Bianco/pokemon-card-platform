"""T7: POST /sealed/ledger/sync — push the ledger to a Google Sheet (full-tab overwrite).

Pins the honest-empty contract at the sync boundary:
- Not configured (no sheet id / no secret) -> 200 with {synced: false, reason: "not_configured"},
  no network call, no raise.
- Configured -> clear the tab range, then write header + rows (idempotent full overwrite).

Session override follows the repo idiom established in test_watchlist_api.py /
test_sealed_ledger_api.py: `app.dependency_overrides[get_session] = lambda: db` (returns
the Session directly, NOT a generator). Routes are mounted at root (no `/api/` prefix) —
TestClient talks to the app directly with no Vite proxy, so it hits `/sealed/ledger/sync`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings


def _client(monkeypatch, db, sheet_id="SHEET123"):
    """FastAPI dependency override matching the repo idiom (see test_sealed_ledger_api.py).

    Monkeypatches `cardplatform.api.settings` so the sync route sees the desired sheet-id
    state; the route reads the module-level `settings` singleton when building the client.
    """
    app = create_app()
    monkeypatch.setattr(
        "cardplatform.api.settings",
        Settings(
            listings_api_key="app-id",
            google_sheet_id=sheet_id,
            google_sheet_tab="Sealed Ledger",
        ),
    )
    # REPO IDIOM: return the Session directly, NOT a generator.
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def test_sync_not_configured_returns_honest_result(db, monkeypatch):
    # No sheet id -> not configured (is_configured() is False without a network call).
    client = _client(monkeypatch, db, sheet_id=None)
    r = client.post("/sealed/ledger/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is False
    assert body["reason"] == "not_configured"


def test_sync_configured_writes_rows(db, monkeypatch):
    client = _client(monkeypatch, db, sheet_id="SHEET123")
    # Log a purchase so the sheet has one data row (plus the header).
    client.post("/sealed/ledger", json={"query": "box", "cost_per_unit": 10.0})

    calls = {"clear": False, "update_body": None}

    class FakeValues:
        def clear(self, spreadsheetId, range):
            calls["clear"] = True
            return self

        def update(self, spreadsheetId, range, valueInputOption, body):
            calls["update_body"] = body
            return self

        def execute(self):
            return {}

    class FakeSpreadsheets:
        def values(self):
            return FakeValues()

    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    # Patch is_configured -> True + _authorize -> dummy (secret file absent in tmp).
    monkeypatch.setattr(
        "cardplatform.sealed.sheets.GoogleSheetsClient.is_configured", lambda self: True
    )
    monkeypatch.setattr(
        "cardplatform.sealed.sheets.GoogleSheetsClient._authorize", lambda self: object()
    )
    # `build` is imported lazily inside sync() from googleapiclient.discovery — patch it
    # there so the lazy name resolution picks up the fake.
    import googleapiclient.discovery as discovery

    monkeypatch.setattr(discovery, "build", lambda *a, **k: FakeService())

    r = client.post("/sealed/ledger/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is True
    assert body["rows"] == 1  # one purchase row (header excluded)
    assert calls["clear"] is True
    assert calls["update_body"]["values"][0][0] == "Date"  # header
    assert calls["update_body"]["values"][1][1] == "box"