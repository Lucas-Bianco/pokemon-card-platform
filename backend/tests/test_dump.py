import json
from pathlib import Path

import httpx
import pytest
import respx

from cardplatform.catalog.dump import DumpClient
from cardplatform.config import Settings


@respx.mock
def test_fetch_sets_decodes_utf8(tmp_path: Path):
    """The dump is UTF-8. Windows defaults to cp1252, which would corrupt this."""
    payload = [{"id": "base1", "name": "Base", "series": "Base"}]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_sets_url).mock(return_value=httpx.Response(200, content=body))

    sets = DumpClient(settings).fetch_sets()

    assert sets[0]["id"] == "base1"


@respx.mock
def test_accented_characters_are_not_mojibaked(tmp_path: Path):
    """Reproduces the real failure mode: bytes are utf-8, but the server *declares*
    a different charset. json.loads(response.text) would honor that declared
    charset and mangle 'Pokémon' into 'PokÃ©mon'; decoding the raw bytes as utf-8
    ourselves does not."""
    payload = [{"id": "base1-4", "name": "Charizard", "supertype": "Pokémon"}]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_cards_url("base1")).mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/plain; charset=iso-8859-1"},
        )
    )

    cards = DumpClient(settings).fetch_cards("base1")

    assert cards[0]["supertype"] == "Pokémon"
    assert "Ã" not in cards[0]["supertype"]


@respx.mock
def test_missing_set_file_returns_empty_list(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_cards_url("nope")).mock(return_value=httpx.Response(404))

    assert DumpClient(settings).fetch_cards("nope") == []


@respx.mock
def test_missing_sets_file_returns_empty_list(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_sets_url).mock(return_value=httpx.Response(404))

    assert DumpClient(settings).fetch_sets() == []


@respx.mock
def test_persistent_server_error_raises_after_retries_exhausted(tmp_path: Path):
    """A silently-empty catalog is worse than a loud failure: unlike the price
    provider, exhausted retries must propagate, not degrade to []."""
    settings = Settings(data_dir=tmp_path, http_max_attempts=2)
    respx.get(settings.dump_cards_url("base1")).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        DumpClient(settings).fetch_cards("base1")
