import json

from cardplatform.config import Settings
from cardplatform.sealed.sheets import GoogleSheetsClient


def _settings(tmp_path, sheet_id="SHEET123"):
    return Settings(data_dir=tmp_path, google_sheet_id=sheet_id, google_sheet_tab="Sealed Ledger")


def _write_secret(path):
    path.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))


def test_not_configured_without_secret(tmp_path):
    s = _settings(tmp_path)
    client = GoogleSheetsClient(s)
    assert client.is_configured() is False


def test_not_configured_without_sheet_id(tmp_path):
    s = _settings(tmp_path, sheet_id=None)
    _write_secret(s.google_client_secret_path)
    assert GoogleSheetsClient(s).is_configured() is False


def test_configured_with_secret_and_sheet_id(tmp_path):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    assert GoogleSheetsClient(s).is_configured() is True


def test_authorize_runs_flow_when_no_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    client = GoogleSheetsClient(s)

    captured = {}

    class FakeCreds:
        def __init__(self, valid=True, expired=False, refresh_token="rt"):
            self.valid = valid
            self.expired = expired
            self.refresh_token = refresh_token

        def to_json(self):
            return json.dumps({"token": "abc", "refresh_token": self.refresh_token})

    class FakeFlow:
        def __init__(self, *a, **kw):
            captured["flow_built"] = True

        def run_local_server(self, port=0):
            captured["ran_browser"] = True
            return FakeCreds()

    def fake_from_file(path, scopes):
        raise FileNotFoundError(path)  # no token yet

    monkeypatch.setattr("cardplatform.sealed.sheets.InstalledAppFlow.from_client_secrets_file", lambda *a, **kw: FakeFlow())
    monkeypatch.setattr("cardplatform.sealed.sheets.Credentials.from_authorized_user_file", fake_from_file)

    creds = client._authorize()
    assert captured["ran_browser"] is True
    assert s.google_token_path.exists()  # token persisted
    assert json.loads(s.google_token_path.read_text())["token"] == "abc"


def test_authorize_loads_existing_valid_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)

    class FakeCreds:
        valid = True
        expired = False
        refresh_token = "rt"

        def to_json(self):
            return json.dumps({"token": "existing"})

    s.google_token_path.write_text(json.dumps({"token": "existing"}))
    monkeypatch.setattr(
        "cardplatform.sealed.sheets.Credentials.from_authorized_user_file",
        lambda path, scopes: FakeCreds(),
    )
    client = GoogleSheetsClient(s)
    creds = client._authorize()
    assert creds.valid is True
    # No browser flow should have run; token file unchanged.
    assert json.loads(s.google_token_path.read_text())["token"] == "existing"


def test_authorize_refreshes_expired_token(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _write_secret(s.google_client_secret_path)
    s.google_token_path.write_text(json.dumps({"token": "old"}))

    refreshed = {"called": False}

    class FakeCreds:
        valid = False
        expired = True
        refresh_token = "rt"

        def refresh(self, req):
            refreshed["called"] = True
            self.valid = True
            self.expired = False

        def to_json(self):
            return json.dumps({"token": "refreshed"})

    monkeypatch.setattr("cardplatform.sealed.sheets.Credentials.from_authorized_user_file", lambda path, scopes: FakeCreds())
    client = GoogleSheetsClient(s)
    creds = client._authorize()
    assert refreshed["called"] is True
    assert creds.valid is True
    assert json.loads(s.google_token_path.read_text())["token"] == "refreshed"


def test_sync_not_configured_returns_honest(tmp_path):
    s = _settings(tmp_path)  # no secret file written
    client = GoogleSheetsClient(s)
    result = client.sync([["Date"], ["row1"]])
    assert result.synced is False
    assert result.reason == "not_configured"
    assert result.rows == 0