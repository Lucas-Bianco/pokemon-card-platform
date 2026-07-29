"""pokemontcg.io price provider.

Measured 2026-07-28: the API returned HTTP 500 for 10 of 12 requests. Retries with
exponential backoff are essential, and total failure must degrade to [] rather than raise.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_exponential

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.provider import PriceQuote

logger = logging.getLogger(__name__)

# Cardmarket has no low/mid/market fields; these are the nearest analogues, not
# equivalents. averageSellPrice and trendPrice are Cardmarket-specific statistics,
# not the same measure as tcgplayer's market/mid — do not average them across sources.
_CARDMARKET_FIELD_MAP = {
    "market": "averageSellPrice",
    "low": "lowPrice",
    "mid": "trendPrice",
}


class _TerminalHttpError(Exception):
    """A 4xx (other than 429) — retrying identical requests will never succeed."""


class PokemonTcgIoProvider:
    name = "pokemontcg.io"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def fetch(self, card_id: str) -> list[PriceQuote]:
        payload = self._get_card(card_id)
        if payload is None:
            return []

        data = payload.get("data") or {}
        quotes: list[PriceQuote] = []
        quotes.extend(self._parse_tcgplayer(card_id, data.get("tcgplayer")))
        quotes.extend(self._parse_cardmarket(card_id, data.get("cardmarket")))
        return quotes

    def _get_card(self, card_id: str) -> dict[str, Any] | None:
        """GET the card, retrying transport errors, 5xx, and 429 only.

        A 404 (unknown/renamed id) or 401/403 (bad key) will never succeed on retry, so
        those raise _TerminalHttpError, which is not in the retry predicate — tenacity
        propagates it after a single attempt instead of burning the full attempt budget.
        """
        headers = {"X-Api-Key": self.settings.api_key} if self.settings.api_key else {}
        url = f"{self.settings.api_base_url}/cards/{card_id}"

        @retry(
            stop=stop_after_attempt(self.settings.http_max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_result(lambda r: r is None),
        )
        def _attempt() -> dict[str, Any] | None:
            try:
                response = httpx.get(
                    url, headers=headers, timeout=self.settings.http_timeout_seconds
                )
            except httpx.HTTPError as exc:
                logger.warning("price fetch transport error for %s: %s", card_id, exc)
                return None
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "price fetch HTTP %s for %s (retryable)", response.status_code, card_id
                )
                return None
            logger.warning(
                "price fetch HTTP %s for %s (terminal, not retrying)",
                response.status_code,
                card_id,
            )
            raise _TerminalHttpError(response.status_code)

        try:
            return _attempt()
        except _TerminalHttpError:
            return None
        except RetryError:
            logger.error(
                "price fetch gave up for %s after %s attempts",
                card_id,
                self.settings.http_max_attempts,
            )
            return None

    @staticmethod
    def _parse_tcgplayer(card_id: str, block: dict[str, Any] | None) -> list[PriceQuote]:
        if not block:
            return []
        updated = block.get("updatedAt")
        quotes = []
        for variant, values in (block.get("prices") or {}).items():
            if not isinstance(values, dict):
                continue
            quotes.append(
                PriceQuote(
                    card_id=card_id,
                    source="tcgplayer",
                    variant=variant,
                    low=values.get("low"),
                    mid=values.get("mid"),
                    high=values.get("high"),
                    market=values.get("market"),
                    source_updated_at=updated,
                )
            )
        return quotes

    @staticmethod
    def _parse_cardmarket(card_id: str, block: dict[str, Any] | None) -> list[PriceQuote]:
        """Cardmarket has no per-variant breakdown and lagged ~4 weeks when measured."""
        if not block:
            return []
        prices = block.get("prices") or {}
        if not prices:
            return []
        return [
            PriceQuote(
                card_id=card_id,
                source="cardmarket",
                variant="aggregate",
                low=prices.get(_CARDMARKET_FIELD_MAP["low"]),
                mid=prices.get(_CARDMARKET_FIELD_MAP["mid"]),
                high=None,
                market=prices.get(_CARDMARKET_FIELD_MAP["market"]),
                source_updated_at=block.get("updatedAt"),
            )
        ]
