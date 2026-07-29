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
