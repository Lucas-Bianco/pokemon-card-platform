"""Fetches the pokemon-tcg-data JSON dump from GitHub.

Used instead of api.pokemontcg.io for catalog data: on 2026-07-28 the API returned
HTTP 500 for 10 of 12 requests, while raw.githubusercontent.com served reliably.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from cardplatform.config import Settings, settings as default_settings


class DumpClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def fetch_sets(self) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_sets_url)

    def fetch_cards(self, set_id: str) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_cards_url(set_id))

    def _get_json(self, url: str) -> list[dict[str, Any]]:
        response = httpx.get(url, timeout=self.settings.http_timeout_seconds, follow_redirects=True)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        # Decode explicitly: httpx may guess, and Windows' cp1252 default turns 'é' into 'Ã©'.
        return json.loads(response.content.decode("utf-8"))
