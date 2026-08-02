"""PkmnPrices graded-price provider (eBay sold comps for PSA/CGC/BGS).

PkmnPrices (https://www.pkmnprices.com/docs) exposes eBay sold listings per
card. Unlike pokemontcg.io's tcgplayer/cardmarket price blocks, it returns
individual sold comps (one row per sale) each carrying a `price`, `grader`,
`grade`, and `sold_at`. There is no per-variant breakdown and no
low/mid/high/market aggregate, so we group the sold comps by (grader, grade)
and compute low/min, high/max, mid/median, market/median ourselves.

Degrade-to-[] philosophy (mirrors PokemonTcgIoProvider):
  * No API key configured -> return [] WITHOUT making a request. This is the
    default state; graded prices are opt-in, never a crash.
  * 404 / 401 (terminal) -> one attempt, then []. A 404 commonly means
    PkmnPrices has no listings for that card id (see id-mapping caveat below).
  * Transport error / 5xx / 429 -> retry with exponential backoff, then [].
  * Unparseable JSON or unexpected shape -> [].
  * NEVER raises.

ID-mapping caveat (documented follow-up, NOT solved here):
  PkmnPrices card ids are the site's own slugs/numeric ids and may NOT match
  this project's `base1-4` pokemontcg.io-style ids. A fetch against a mismatched
  id 404s, which this adapter honestly converts to []. A card-id mapping layer
  (project id -> PkmnPrices id) is a documented follow-up; until it exists,
  graded prices are simply unavailable for ids PkmnPrices does not recognize.
  Do NOT build the mapping here — T4 is graded *price* data only.

Pagination follow-up: only the first page of sold comps (up to 20 listings) is
fetched. PkmnPrices paginates via `pagination.next_cursor`; looping pages would
give a more stable median for actively-traded cards but adds retry-surface and
is out of scope for T4. A single page grouped into (grader, grade) buckets is
enough to seed a graded-price baseline.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

import httpx
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_exponential

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.graded_provider import GradedPriceQuote

logger = logging.getLogger(__name__)

# PkmnPrices does not break sold comps down by printing variant (holofoil /
# reverseHolofoil / normal). The whole grade bucket is one aggregate series,
# so we store it under a single "aggregate" variant — the same honest
# convention PokemonTcgIoProvider uses for cardmarket's single-figure card.
_DEFAULT_VARIANT = "aggregate"


class _TerminalHttpError(Exception):
    """A 4xx (other than 429) — retrying identical requests will never succeed."""


class PkmnPricesProvider:
    name = "pkmnprices"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def fetch_graded(self, card_id: str) -> list[GradedPriceQuote]:
        # No key configured is the default state: graded prices are opt-in.
        # Return [] WITHOUT touching the network — never crash, never raise.
        if not self.settings.graded_price_api_key:
            return []

        payload = self._get_listings(card_id)
        if payload is None:
            return []

        try:
            return self._parse(card_id, payload)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            # Unexpected JSON shape is an honest "unavailable", not a crash.
            logger.warning("pkmnprices parse failure for %s: %s", card_id, exc)
            return []

    def _get_listings(self, card_id: str) -> dict[str, Any] | None:
        """GET the eBay sold-listings page, retrying transport/5xx/429 only.

        Mirrors PokemonTcgIoProvider._get_card exactly: 404/401 raise
        _TerminalHttpError (one attempt only); 5xx/429/transport return None and
        tenacity retries until the attempt budget is exhausted, then we degrade
        to [].
        """
        headers = {"X-API-Key": self.settings.graded_price_api_key}
        url = (
            f"{self.settings.graded_price_base_url}/cards/{card_id}/listings/ebay"
            "?graded=true"
        )

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
                logger.warning("graded price fetch transport error for %s: %s", card_id, exc)
                return None
            if response.status_code == 200:
                try:
                    return response.json()
                except (httpx.DecodingError, ValueError) as exc:
                    # 200 with a non-JSON body is not retryable — degrade to [].
                    logger.warning("graded price fetch bad JSON for %s: %s", card_id, exc)
                    return None
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "graded price fetch HTTP %s for %s (retryable)",
                    response.status_code,
                    card_id,
                )
                return None
            logger.warning(
                "graded price fetch HTTP %s for %s (terminal, not retrying)",
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
                "graded price fetch gave up for %s after %s attempts",
                card_id,
                self.settings.http_max_attempts,
            )
            return None

    @staticmethod
    def _parse(card_id: str, payload: dict[str, Any]) -> list[GradedPriceQuote]:
        """Group sold comps by (grader, grade) into one quote per bucket.

        PkmnPrices returns `{"data": [ {price, grader, grade, sold_at, ...} ]}`.
        Listings missing grader/grade or with an unparseable grade/price are
        skipped rather than fabricated into a bucket.
        """
        data = payload.get("data")
        if not isinstance(data, list):
            return []

        # Bucket prices by (grader, grade) so each bucket becomes one quote.
        # Also track the most recent sold_at per bucket as the freshness stamp.
        buckets: dict[tuple[str, float], dict[str, Any]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            grader = item.get("grader")
            grade_raw = item.get("grade")
            price = item.get("price")
            if grader is None or grade_raw is None or price is None:
                continue
            try:
                grade = float(grade_raw)
            except (TypeError, ValueError):
                continue
            try:
                price_f = float(price)
            except (TypeError, ValueError):
                continue
            key = (str(grader), grade)
            bucket = buckets.setdefault(
                key, {"prices": [], "latest_sold_at": ""}
            )
            bucket["prices"].append(price_f)
            sold_at = item.get("sold_at") or ""
            if str(sold_at) > bucket["latest_sold_at"]:
                bucket["latest_sold_at"] = str(sold_at)

        quotes: list[GradedPriceQuote] = []
        for (grader, grade), bucket in buckets.items():
            prices = bucket["prices"]
            if not prices:
                continue
            median = statistics.median(prices)
            quotes.append(
                GradedPriceQuote(
                    card_id=card_id,
                    grader=grader,
                    grade=grade,
                    variant=_DEFAULT_VARIANT,
                    low=min(prices),
                    mid=median,
                    high=max(prices),
                    market=median,
                    source="pkmnprices",
                    source_updated_at=bucket["latest_sold_at"] or None,
                )
            )
        return quotes