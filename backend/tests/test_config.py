from pathlib import Path

from cardplatform.config import Settings


def test_defaults_point_at_data_dir():
    s = Settings()
    assert s.data_dir.name == "data"
    assert s.db_path.suffix == ".sqlite3"
    assert s.db_path.parent == s.data_dir


def test_database_url_is_sqlite():
    s = Settings()
    assert s.database_url.startswith("sqlite:///")


def test_dump_urls_are_wellformed():
    s = Settings()
    assert s.dump_sets_url.endswith("/sets/en.json")
    assert "pokemon-tcg-data" in s.dump_sets_url
    assert s.dump_cards_url("base1").endswith("/cards/en/base1.json")


def test_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CARDPLATFORM_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.data_dir == tmp_path
