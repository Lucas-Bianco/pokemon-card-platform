"""Application settings. Override any field with a CARDPLATFORM_ prefixed env var."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardplatform.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def dump_sets_url(self) -> str:
        return f"{self.dump_base_url}/sets/en.json"

    def dump_cards_url(self, set_id: str) -> str:
        return f"{self.dump_base_url}/cards/en/{set_id}.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
