"""Application settings. Override any field with a CARDPLATFORM_ prefixed env var."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

def _find_repo_root() -> Path:
    """Walk up for a repo marker. Falls back to cwd when installed as a wheel.

    A fixed `parents[N]` index breaks on a non-editable install: from
    `.venv/Lib/site-packages/cardplatform/config.py`, that index resolves inside the
    venv and `data_dir` silently lands in `.venv/data`, vanishing on rebuild.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists() or (candidate / "pytest.ini").exists():
            return candidate
    return Path.cwd()


_REPO_ROOT = _find_repo_root()
_DUMP_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDPLATFORM_", extra="ignore")

    data_dir: Path = Field(default=_REPO_ROOT / "data")

    # Catalog dump (GitHub). Used instead of the API, which fails ~83% of requests.
    dump_base_url: str = Field(default=_DUMP_BASE)

    # Live price API. Only used for prices; never for bulk catalog loading.
    api_base_url: str = Field(default="https://api.pokemontcg.io/v2")
    api_key: str | None = Field(default=None)

    # The API is unreliable, so retry generously.
    http_timeout_seconds: float = Field(default=30.0)
    http_max_attempts: int = Field(default=8)

    # --- recognition (Phase 1a) ---
    # ViT-B-32/laion2b measured at 2.2 ms/card on an RTX 5070 Ti: ~0.7 min for the
    # full 20,444-card catalog, 512-d vectors, ~42 MB index.
    encoder_model: str = Field(default="ViT-B-32")
    encoder_pretrained: str = Field(default="laion2b_s34b_b79k")
    rectified_size: tuple[int, int] = Field(default=(600, 825))
    visual_top_k: int = Field(default=5)

    # --- grading (Phase 3b) ---
    # PSA bulk ~$25 per card. T5 uses this as the cost basis when computing the
    # "grading upside" spread (graded market price minus raw price minus fee).
    grading_fee: float = Field(default=25.0)

    # Graded-price source (PkmnPrices eBay sold comps). Opt-in: when the key is
    # None (the default) the provider returns [] without touching the network,
    # so graded prices are simply unavailable until a key is configured. Base
    # URL per https://www.pkmnprices.com/docs (endpoint /v1/cards/:id/listings/ebay).
    graded_price_api_key: str | None = Field(default=None)
    graded_price_base_url: str = Field(default="https://api.pkmnprices.com/v1")

    # Listings source (eBay Browse API item_summary/search). Opt-in: when the
    # key is None (the default) the provider returns [] without touching the
    # network, so listings are simply unavailable until a key is configured.
    # Base URL per https://developer.ebay.com/api-docs/buy/browse/resources/item_summary
    listings_api_key: str | None = Field(default=None)
    listings_base_url: str = Field(default="https://api.ebay.com/buy/browse/v1")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardplatform.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def dump_sets_url(self) -> str:
        return f"{self.dump_base_url}/sets/en.json"

    @property
    def reference_image_dir(self) -> Path:
        return self.data_dir / "reference_images"

    @property
    def scan_image_dir(self) -> Path:
        return self.data_dir / "scans"

    @property
    def rectified_image_dir(self) -> Path:
        """Deskewed, border-cropped scan crops written by T2's recognize flow."""
        return self.data_dir / "rectified"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "card_index.faiss"

    @property
    def index_ids_path(self) -> Path:
        return self.data_dir / "card_index_ids.json"

    def dump_cards_url(self, set_id: str) -> str:
        return f"{self.dump_base_url}/cards/en/{set_id}.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
