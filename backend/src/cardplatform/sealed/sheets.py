"""Google Sheets sync client (OAuth browser sign-in).

Local-first, opt-in: the sealed ledger is the source of truth; Sheets is a mirror. This
module handles credential lifecycle (load/refresh/authorize via InstalledAppFlow) + an
`is_configured()` honest-empty gate. The sync *write* is added in T7.

Token + client secret are stored under data/ (gitignored) — never committed. The OAuth flow
opens the user's browser (flow.run_local_server) — this is a local-first desktop app, not a
headless server.
"""

from __future__ import annotations

from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from cardplatform.config import Settings, settings as default_settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    @property
    def secret_path(self) -> Path:
        return self.settings.google_client_secret_path

    @property
    def token_path(self) -> Path:
        return self.settings.google_token_path

    def is_configured(self) -> bool:
        """True iff a client secret file exists AND a spreadsheet id is set. No network call."""
        return bool(self.settings.google_sheet_id) and self.secret_path.exists()

    def _authorize(self):
        # Request is imported lazily — it is not monkeypatched by tests and pulls in a small
        # transport stack; Credentials / InstalledAppFlow are module-level imports so tests
        # can monkeypatch them on this module's namespace.
        from google.auth.transport.requests import Request

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.secret_path), SCOPES)
                creds = flow.run_local_server(port=0)
            self.token_path.write_text(creds.to_json())
        return creds