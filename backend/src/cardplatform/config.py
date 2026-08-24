"""Application settings. Override any field with a CARDPLATFORM_ prefixed env var."""

from pathlib import Path

from pydantic import Field, field_validator
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
    # `.env` sits beside the repo root and is gitignored. Loading it here is what makes
    # `CARDPLATFORM_DATA_DIR` (and the API keys) take effect without exporting them in
    # every shell — before this, the file existed but nothing read it. Precedence is
    # unchanged where it matters: constructor args and real env vars both still win, so
    # the tests that pass `data_dir=tmp_path` or monkeypatch the env are unaffected.
    model_config = SettingsConfigDict(
        env_prefix="CARDPLATFORM_",
        extra="ignore",
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
    )

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

    # Phase 4: parallel OCR workers for recognize_many. RapidOCR is not thread-safe,
    # so each worker constructs its own engine. Capped to [1, 4] — OCR is ~1 s/crop
    # and each engine is a meaningful memory cost.
    batch_ocr_workers: int = Field(default=2)

    @field_validator("batch_ocr_workers")
    @classmethod
    def _clamp_batch_ocr_workers(cls, v: int) -> int:
        return max(1, min(4, int(v)))

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

    # Listings source (eBay Finding API findItemsByKeywords). Opt-in: when the
    # key is None (the default) the provider returns [] without touching the
    # network, so listings are simply unavailable until a key is configured.
    # The Finding API takes a single SECURITY-APPNAME (App ID) as a query
    # param — no OAuth — so Lucas's free eBay developer App ID works directly.
    # Base URL per https://developer.ebay.com/Devzone/finding/CallRefType/index.html
    listings_api_key: str | None = Field(default=None)
    listings_base_url: str = Field(default="https://svcs.ebay.com/services/search/FindingService/v1")

    # --- alerts (Phase 3c) ---
    # Web Push (VAPID) keypair. Opt-in: when both keys are None (the default) the
    # notifier skips push entirely and never touches the network. Generate with
    # `cardplatform gen-vapid` and set as CARDPLATFORM_VAPID_PUBLIC_KEY /
    # CARDPLATFORM_VAPID_PRIVATE_KEY. `vapid_subject` is the JWT "sub" claim
    # (a mailto: or https:// URL per the Web Push spec).
    vapid_public_key: str | None = Field(default=None)
    vapid_private_key: str | None = Field(default=None)
    vapid_subject: str | None = Field(default=None)

    # Email (SMTP) delivery. Opt-in: when smtp_host is None (the default) the
    # notifier skips email entirely. This is a single-user local-first app, so
    # email is delivered to the configured smtp_from address (self-loop); a
    # per-watch recipient is a follow-up.
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_user: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)

    # Alert poll cadence and per-watch cooldown. The engine reads cooldown_min
    # defensively (getattr default 60); owning it here keeps the value in one
    # place. poll_min is the T5 poll loop interval (informational here; the loop
    # reads it directly from settings).
    alert_poll_min: int = Field(default=15)
    alert_cooldown_min: int = Field(default=60)

    # --- deals (Phase 05 / rip-vs-flip) ---
    # Thresholds filter noise without manufacturing deals. A listing is a `rip`
    # when rip_edge >= deal_rip_min_abs AND >= deal_rip_min_pct * raw_market.
    # A listing is a `flip` when flip_edge_to_10 >= deal_flip_min_abs (grading
    # fee + meaningful profit). Edges are indicative leads, not arbitrage.
    deal_rip_min_abs: float = Field(default=2.0)
    deal_rip_min_pct: float = Field(default=0.10)
    deal_flip_min_abs: float = Field(default=20.0)

    # Phase 05c — sealed-product flip-edge (reuses CARDPLATFORM_LISTINGS_API_KEY;
    # sealed products ARE eBay listings, so no separate sealed key is needed).
    sealed_flip_min_abs: float = 20.0
    sealed_flip_min_pct: float = 0.05
    sealed_sold_comp_limit: int = 10  # how many sold comps drive the market median

    @field_validator("sealed_sold_comp_limit")
    @classmethod
    def _clamp_sealed_sold_comp_limit(cls, v: int) -> int:
        return max(1, min(v, 100))

    # Phase 05d — Google Sheets sync (OAuth browser sign-in; local-first, opt-in).
    google_sheet_id: str | None = Field(default=None)
    google_sheet_tab: str = Field(default="Sealed Ledger")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardplatform.sqlite3"

    @property
    def google_client_secret_path(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def google_token_path(self) -> Path:
        return self.data_dir / "google_token.json"

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
