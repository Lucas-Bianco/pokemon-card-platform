"""T4: PkmnPricesProvider — graded sold-comp parsing + degrade-to-[] guarantees.

Mirrors test_price_provider.py's respx-mocked-httpx pattern. No real network:
every request is mocked via respx. The provider must NEVER raise — every
failure mode (no key, 404, transport error, 5xx after retries, bad JSON,
unexpected shape) degrades to [].
"""

from __future__ import annotations

import httpx
import respx

from cardplatform.config import Settings
from cardplatform.prices.graded_provider import GradedPriceQuote
from cardplatform.prices.pkmnprices import PkmnPricesProvider

# PkmnPrices eBay sold-listings shape per https://www.pkmnprices.com/docs.
# Each item is one sale; the provider groups by (grader, grade).
SOLD_RESPONSE = {
    "data": [
        {"id": 1, "title": "PSA 10 Charizard", "price": 275, "grader": "PSA",
         "grade": "10", "sold_at": "2025-01-14"},
        {"id": 2, "title": "PSA 10 Charizard", "price": 300, "grader": "PSA",
         "grade": "10", "sold_at": "2025-01-20"},
        {"id": 3, "title": "PSA 9 Charizard", "price": 120, "grader": "PSA",
         "grade": "9", "sold_at": "2025-01-18"},
        {"id": 4, "title": "CGC 9.5 Charizard", "price": 150, "grader": "CGC",
         "grade": "9.5", "sold_at": "2025-01-16"},
    ],
    "pagination": {"has_more": False, "next_cursor": None, "count": 4},
}


def _url(settings: Settings, card_id: str) -> str:
    return (
        f"{settings.graded_price_base_url}/cards/{card_id}/listings/ebay?graded=true"
    )


def test_no_api_key_returns_empty_without_network(monkeypatch):
    """Default state: no key configured. Provider must NOT call httpx at all."""
    settings = Settings(graded_price_api_key=None)

    called = {"count": 0}

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        called["count"] += 1
        raise AssertionError("httpx.get must not be called when no API key is set")

    monkeypatch.setattr(httpx, "get", _fail_if_called)

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")

    assert quotes == []
    assert called["count"] == 0


@respx.mock
def test_parses_sold_listings_grouped_by_grader_and_grade():
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json=SOLD_RESPONSE)
    )

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")

    # Three buckets: PSA 10, PSA 9, CGC 9.5.
    by_key = {(q.grader, q.grade): q for q in quotes}
    assert set(by_key) == {("PSA", 10.0), ("PSA", 9.0), ("CGC", 9.5)}

    psa10 = by_key[("PSA", 10.0)]
    assert psa10.market == 287.5  # median of [275, 300]
    assert psa10.low == 275.0
    assert psa10.high == 300.0
    assert psa10.mid == 287.5
    assert psa10.source == "pkmnprices"
    assert psa10.variant == "aggregate"
    assert psa10.source_updated_at == "2025-01-20"  # most recent sold_at in bucket
    assert isinstance(psa10, GradedPriceQuote)


@respx.mock
def test_sends_api_key_header():
    settings = Settings(graded_price_api_key="secret-graded-key")
    route = respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json=SOLD_RESPONSE)
    )

    PkmnPricesProvider(settings).fetch_graded("base1-4")

    sent = route.calls.last.request
    assert sent.headers["X-API-Key"] == "secret-graded-key"


@respx.mock
def test_404_is_not_retried_and_returns_empty():
    """A 404 commonly means PkmnPrices has no listing for that project id
    (id-mapping mismatch) — one attempt, then [] (honest unavailable)."""
    settings = Settings(graded_price_api_key="key-123", http_max_attempts=5)
    route = respx.get(_url(settings, "missing-1")).mock(
        return_value=httpx.Response(404)
    )

    quotes = PkmnPricesProvider(settings).fetch_graded("missing-1")

    assert quotes == []
    assert route.call_count == 1


@respx.mock
def test_401_is_not_retried():
    settings = Settings(graded_price_api_key="bad-key", http_max_attempts=5)
    route = respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(401)
    )

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []
    assert route.call_count == 1


@respx.mock
def test_500_is_retried_up_to_max_attempts():
    settings = Settings(graded_price_api_key="key-123", http_max_attempts=3)
    route = respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(500)
    )

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []
    assert route.call_count == 3


@respx.mock
def test_429_is_retried_up_to_max_attempts():
    settings = Settings(graded_price_api_key="key-123", http_max_attempts=3)
    route = respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(429)
    )

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []
    assert route.call_count == 3


@respx.mock
def test_retries_then_succeeds_on_flaky_api():
    settings = Settings(graded_price_api_key="key-123", http_max_attempts=4)
    route = respx.get(_url(settings, "base1-4"))
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json=SOLD_RESPONSE),
    ]

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")
    assert len(quotes) == 3
    assert route.call_count == 3


@respx.mock
def test_transport_error_degrades_to_empty(monkeypatch):
    """A connection-level error is retryable; after the budget is exhausted it
    degrades to [] rather than raising."""
    settings = Settings(graded_price_api_key="key-123", http_max_attempts=2)

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []


@respx.mock
def test_bad_json_degrades_to_empty():
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>",
                                     headers={"content-type": "text/html"})
    )

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []


@respx.mock
def test_unexpected_shape_degrades_to_empty():
    """A 200 with a shape we don't recognize (no `data` list) is honest [], not a crash."""
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    assert PkmnPricesProvider(settings).fetch_graded("base1-4") == []


@respx.mock
def test_listings_missing_grader_or_grade_are_skipped():
    """Ungraded rows (grader/grade null) cannot populate a graded bucket — skip them."""
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"id": 1, "price": 100, "grader": None, "grade": None, "sold_at": "2025-01-14"},
                {"id": 2, "price": 200, "grader": "PSA", "grade": "10", "sold_at": "2025-01-15"},
            ],
        })
    )

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")
    assert len(quotes) == 1
    assert quotes[0].grader == "PSA"
    assert quotes[0].grade == 10.0


@respx.mock
def test_unparseable_grade_is_skipped():
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"id": 1, "price": 100, "grader": "PSA", "grade": "mint", "sold_at": "2025-01-14"},
                {"id": 2, "price": 200, "grader": "PSA", "grade": "10", "sold_at": "2025-01-15"},
            ],
        })
    )

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")
    assert len(quotes) == 1
    assert quotes[0].grade == 10.0


@respx.mock
def test_missing_sold_at_uses_empty_string_sentinel():
    """When no sold_at is present, source_updated_at is None -> service stores ''
    (the dedupe sentinel)."""
    settings = Settings(graded_price_api_key="key-123")
    respx.get(_url(settings, "base1-4")).mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"id": 1, "price": 200, "grader": "PSA", "grade": "10", "sold_at": None},
            ],
        })
    )

    quotes = PkmnPricesProvider(settings).fetch_graded("base1-4")
    assert len(quotes) == 1
    assert quotes[0].source_updated_at is None