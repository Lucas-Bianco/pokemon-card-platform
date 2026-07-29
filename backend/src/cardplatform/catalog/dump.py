"""Fetches the pokemon-tcg-data JSON dump from GitHub.

Used instead of api.pokemontcg.io for catalog data: on 2026-07-28 the API returned
HTTP 500 for 10 of 12 requests, while raw.githubusercontent.com served reliably.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from cardplatform.config import Settings, settings as default_settings


class DumpClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        # One client reused across all requests: Task 11's sync issues ~175
        # sequential requests (1 sets file + ~174 per-set card files), and a fresh
        # httpx.get() per call would mean a fresh TLS handshake each time.
        self._client = httpx.Client(
            timeout=self.settings.http_timeout_seconds, follow_redirects=True
        )

    def fetch_sets(self) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_sets_url)

    def fetch_cards(self, set_id: str) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_cards_url(set_id))

    def _get_json(self, url: str) -> list[dict[str, Any]]:
        response = self._get_with_retry(url)
        if response.status_code == 404:
            return []
        # Decode explicitly rather than json.loads(response.text): httpx already
        # defaults to utf-8 when a response carries no charset, so that part isn't
        # the risk. The risk is a server that *declares* the wrong charset (e.g.
        # `content-type: text/plain; charset=iso-8859-1`) for what are actually
        # utf-8 bytes -- `.text` honors that declared charset and mangles accented
        # names ('Pokémon' -> 'PokÃ©mon'). Decoding the raw bytes as utf-8 ourselves
        # ignores a mis-declared charset entirely.
        return json.loads(response.content.decode("utf-8"))

    def _get_with_retry(self, url: str) -> httpx.Response:
        @retry(
            stop=stop_after_attempt(self.settings.http_max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        )
        def _attempt() -> httpx.Response:
            response = self._client.get(url)
            # A missing set file is expected data, not a transient failure: don't
            # retry it and don't raise, just let the caller treat it as [].
            if response.status_code != 404:
                response.raise_for_status()
            return response

        return _attempt()
