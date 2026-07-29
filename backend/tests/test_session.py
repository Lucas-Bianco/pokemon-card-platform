from pathlib import Path

from sqlalchemy import inspect

from cardplatform.config import Settings
from cardplatform.db.session import Database


def test_init_creates_file_and_tables(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(settings)
    database.create_all()

    assert settings.db_path.exists()
    tables = set(inspect(database.engine).get_table_names())
    assert {"cards", "card_sets", "price_snapshots", "collection_items"} <= tables


def test_session_is_usable(tmp_path: Path):
    from cardplatform.db.models import CardSet

    database = Database(Settings(data_dir=tmp_path))
    database.create_all()

    with database.session() as s:
        s.add(CardSet(id="sv1", name="Scarlet & Violet", series="Scarlet & Violet"))
        s.commit()

    with database.session() as s:
        assert s.get(CardSet, "sv1").name == "Scarlet & Violet"
