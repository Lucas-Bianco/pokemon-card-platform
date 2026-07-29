"""Engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Base


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.settings.ensure_dirs()
        self.engine: Engine = create_engine(self.settings.database_url)
        _enable_sqlite_pragmas(self.engine)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._factory() as s:
            yield s


def _enable_sqlite_pragmas(engine: Engine) -> None:
    """WAL improves concurrent reads; foreign_keys is off by default in SQLite.

    No-op on non-SQLite engines so a future Postgres swap doesn't choke on these
    pragmas (Postgres doesn't understand `PRAGMA journal_mode=WAL`).
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
