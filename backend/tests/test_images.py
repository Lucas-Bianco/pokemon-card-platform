import httpx
import respx
from PIL import Image

from cardplatform.config import Settings
from cardplatform.recognition.images import ReferenceImageCache


def _png_bytes(color=(200, 30, 30)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (60, 82), color).save(buf, "PNG")
    return buf.getvalue()


def test_path_for_uses_card_id_not_url_extension(tmp_path):
    """661 catalog URLs end in '/small' with no extension. Deriving the filename
    from the URL would corrupt 3% of the cache."""
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    path = cache.path_for("sv8pt5-160")

    assert path.name == "sv8pt5-160.png"
    assert path.parent == tmp_path / "reference_images"


@respx.mock
def test_fetch_downloads_and_stores(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/base1/4.png"
    respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    path = cache.fetch("base1-4", url)

    assert path.exists()
    assert Image.open(path).size == (60, 82)


@respx.mock
def test_fetch_is_skipped_when_already_cached(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.scrydex.com/whatever/small"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    cache.fetch("sv8pt5-160", url)
    cache.fetch("sv8pt5-160", url)

    assert route.call_count == 1


@respx.mock
def test_extensionless_url_still_cached(tmp_path):
    """Guards the two-CDN / no-extension case explicitly."""
    settings = Settings(data_dir=tmp_path)
    url = "https://images.scrydex.com/abc/small"
    respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))
    cache = ReferenceImageCache(settings)

    path = cache.fetch("me2pt5-234", url)

    assert path.name == "me2pt5-234.png"
    assert Image.open(path).size == (60, 82)


@respx.mock
def test_failed_download_returns_none_and_writes_nothing(tmp_path):
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/nope/1.png"
    respx.get(url).mock(return_value=httpx.Response(404))
    cache = ReferenceImageCache(settings)

    assert cache.fetch("nope-1", url) is None
    assert not cache.path_for("nope-1").exists()


@respx.mock
def test_partial_write_is_not_left_behind_on_corrupt_response(tmp_path):
    """A truncated body must not leave an unopenable file that later looks cached."""
    settings = Settings(data_dir=tmp_path)
    url = "https://images.pokemontcg.io/bad/1.png"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"not-an-image"))
    cache = ReferenceImageCache(settings)

    assert cache.fetch("bad-1", url) is None
    assert not cache.path_for("bad-1").exists()


def test_ordinary_card_ids_are_not_rewritten(tmp_path):
    """Sanitizing must not invalidate the 20,442 ids that were already fine."""
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    assert cache.path_for("base1-4").name == "base1-4.png"
    assert cache.path_for("sv8pt5-160").name == "sv8pt5-160.png"


def test_illegal_filename_ids_are_distinct_and_writable(tmp_path):
    """ex10-! and ex10-? are the only two ids in the 20,444-card catalog with
    characters outside [A-Za-z0-9_.-]. '?' is illegal in NTFS, and a single
    replacement char would collapse both onto the same file."""
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    bang = cache.path_for("ex10-!")
    question = cache.path_for("ex10-?")

    assert bang.name == "ex10-%21.png"
    assert question.name == "ex10-%3F.png"
    assert bang != question


@respx.mock
def test_illegal_filename_ids_round_trip_through_fetch(tmp_path):
    settings = Settings(data_dir=tmp_path)
    cache = ReferenceImageCache(settings)

    for card_id in ("ex10-!", "ex10-?"):
        url = f"https://images.pokemontcg.io/ex10/{card_id}.png"
        respx.get(url).mock(return_value=httpx.Response(200, content=_png_bytes()))

        path = cache.fetch(card_id, url)

        assert path is not None, card_id
        assert path.exists()
        assert cache.is_cached(card_id)
        assert cache.load(card_id).size == (60, 82)


def test_is_cached_tracks_the_stored_file(tmp_path):
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    assert cache.is_cached("base1-4") is False
    cache.path_for("base1-4").write_bytes(_png_bytes())
    assert cache.is_cached("base1-4") is True


def test_load_returns_none_for_a_missing_card(tmp_path):
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))

    assert cache.load("base1-4") is None


def test_load_round_trips_a_valid_image(tmp_path):
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))
    cache.path_for("base1-4").write_bytes(_png_bytes())

    image = cache.load("base1-4")

    assert image is not None
    assert image.size == (60, 82)
    assert image.mode == "RGB"


def test_load_discards_a_truncated_cache_entry(tmp_path):
    """One interrupted save must not permanently poison a card: is_cached would say
    True forever, so fetch never retries and every later index build crashes."""
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))
    path = cache.path_for("base1-4")
    path.write_bytes(_png_bytes()[:40])  # header intact, pixel data cut off

    assert cache.load("base1-4") is None
    assert not path.exists()  # deleted, so the next fetch heals it


def test_load_discards_a_zero_byte_cache_entry(tmp_path):
    cache = ReferenceImageCache(Settings(data_dir=tmp_path))
    path = cache.path_for("base1-4")
    path.write_bytes(b"")

    assert cache.load("base1-4") is None
    assert not path.exists()
