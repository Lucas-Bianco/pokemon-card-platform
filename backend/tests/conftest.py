import os

import pytest
from sqlalchemy.orm import Session

from cardplatform.config import Settings
from cardplatform.db.session import Database


@pytest.fixture(autouse=True)
def _no_ambient_cardplatform_env(monkeypatch):
    """Strip CARDPLATFORM_* env vars so ambient host env can't leak into tests."""
    for key in list(os.environ):
        if key.startswith("CARDPLATFORM_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def database(tmp_path):
    db = Database(Settings(data_dir=tmp_path))
    db.create_all()
    return db


@pytest.fixture
def engine(database):
    return database.engine


@pytest.fixture
def db(database) -> Session:
    with database.session() as session:
        yield session
