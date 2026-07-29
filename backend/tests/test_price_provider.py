import httpx
import respx

from cardplatform.config import Settings
from cardplatform.prices.pokemontcg import PokemonTcgIoProvider
from cardplatform.prices.provider import PriceQuote

CARD_RESPONSE = {
    "data": {
        "id": "hgss4-1",
        "tcgplayer": {
            "updatedAt": "2026/07/28",
            "prices": {
                "holofoil": {"low": 6.5, "mid": 10.63, "high": 80.34, "market": 9.71},
                "reverseHolofoil": {"low": 6.61, "mid": 15.52, "high": 250.0, "market": 13.41},
            },
        },
        "cardmarket": {
            "updatedAt": "2026/07/01",
            "prices": {"averageSellPrice": 2.67, "lowPrice": 0.44, "trendPrice": 3.64},
        },
    }
}


@respx.mock
def test_parses_per_variant_tcgplayer_prices():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    holo = next(q for q in quotes if q.source == "tcgplayer" and q.variant == "holofoil")
    assert holo.market == 9.71
    assert holo.low == 6.5
    assert holo.source_updated_at == "2026/07/28"

    reverse = next(q for q in quotes if q.variant == "reverseHolofoil")
    assert reverse.market == 13.41
    assert isinstance(reverse, PriceQuote)


@respx.mock
def test_parses_cardmarket_as_separate_source():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    cm = next(q for q in quotes if q.source == "cardmarket")
    assert cm.market == 2.67
    assert cm.source_updated_at == "2026/07/01"


@respx.mock
def test_retries_then_succeeds_on_flaky_api():
    """The live API failed 10 of 12 requests on 2026-07-28. Retry is mandatory."""
    settings = Settings(http_max_attempts=4)
    route = respx.get(f"{settings.api_base_url}/cards/hgss4-1")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json=CARD_RESPONSE),
    ]

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    assert len(quotes) > 0
    assert route.call_count == 3


@respx.mock
def test_gives_up_after_max_attempts():
    settings = Settings(http_max_attempts=3)
    respx.get(f"{settings.api_base_url}/cards/x-1").mock(return_value=httpx.Response(500))

    quotes = PokemonTcgIoProvider(settings).fetch("x-1")

    assert quotes == []


@respx.mock
def test_card_with_no_price_block_returns_empty():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/x-2").mock(
        return_value=httpx.Response(200, json={"data": {"id": "x-2"}})
    )

    assert PokemonTcgIoProvider(settings).fetch("x-2") == []


@respx.mock
def test_404_is_not_retried():
    """A 404 (unknown/renamed card id) will never succeed on retry — one request only."""
    settings = Settings(http_max_attempts=5)
    route = respx.get(f"{settings.api_base_url}/cards/missing-1").mock(
        return_value=httpx.Response(404)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("missing-1")

    assert quotes == []
    assert route.call_count == 1


@respx.mock
def test_401_is_not_retried():
    """A bad API key will never succeed on retry — one request only."""
    settings = Settings(http_max_attempts=5)
    route = respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(401)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    assert quotes == []
    assert route.call_count == 1


@respx.mock
def test_500_is_retried_up_to_max_attempts():
    settings = Settings(http_max_attempts=3)
    route = respx.get(f"{settings.api_base_url}/cards/x-1").mock(return_value=httpx.Response(500))

    quotes = PokemonTcgIoProvider(settings).fetch("x-1")

    assert quotes == []
    assert route.call_count == 3


@respx.mock
def test_429_is_retried_up_to_max_attempts():
    settings = Settings(http_max_attempts=3)
    route = respx.get(f"{settings.api_base_url}/cards/x-1").mock(return_value=httpx.Response(429))

    quotes = PokemonTcgIoProvider(settings).fetch("x-1")

    assert quotes == []
    assert route.call_count == 3


@respx.mock
def test_no_api_key_header_sent_when_key_not_configured():
    settings = Settings(api_key=None)
    route = respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    PokemonTcgIoProvider(settings).fetch("hgss4-1")

    sent = route.calls.last.request
    assert "X-Api-Key" not in sent.headers


@respx.mock
def test_api_key_header_sent_when_key_configured():
    settings = Settings(api_key="secret-key-123")
    route = respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    PokemonTcgIoProvider(settings).fetch("hgss4-1")

    sent = route.calls.last.request
    assert sent.headers["X-Api-Key"] == "secret-key-123"
