"""Idempotent schema migrations for the no-Alembic project.

This project has no Alembic: `Base.metadata.create_all()` creates new tables at
startup but never ALTERs existing ones, so a populated DB cannot gain columns.
`run_migrations` fills that gap with `ALTER TABLE ... ADD COLUMN` statements that
are checked against `PRAGMA table_info` before running, so each is a no-op once
applied. New tables do NOT belong here (create_all handles them); only ALTERs to
existing tables.

Every addition is nullable with no default: a NOT NULL column added to a
non-empty table would fail mid-migration and leave the DB half-migrated.

Two failure classes are split deliberately:
- Programming errors (a typo'd table name in `_ADDITIVE_COLUMNS`) raise loudly,
  because otherwise PRAGMA returns an empty column set every startup and the
  ALTER is silently swallowed as a warning — the column never appears and the
  bug is invisible. A loud raise makes a registry typo surface on first run.
- Transient errors (locked DB, disk full) are `OperationalError`s: logged at
  warning and skipped so the rest of the run still applies and the next startup
  retries the missed column. This keeps "partial run recoverable" for the
  failures that actually can recover.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# Registry of additive column migrations. Append here in future tasks. Each
# entry is (table, column, sqlite_type). Columns are nullable, no NOT NULL, no
# default.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("scan_logs", "rectified_path", "VARCHAR"),
    ("scan_logs", "variant", "VARCHAR"),
)


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def run_migrations(engine: Engine) -> None:
    """Add any missing columns in `_ADDITIVE_COLUMNS` to existing tables.

    Safe to call repeatedly; safe on a fresh DB; safe on a DB that already has
    every column. Raises ``ValueError`` if a registry entry names a table that
    does not exist (a programming error that should not be silently swallowed);
    logs and continues on ``OperationalError`` (transient: locked DB, disk full).
    """
    with engine.begin() as conn:
        # Validate registry table names up front: a typo here would otherwise make
        # PRAGMA return an empty column set every run, so the ALTER is attempted
        # and then swallowed by the broad except — the column never appears and
        # the bug is invisible on every startup. Raise loudly instead.
        actual_tables = set(inspect(engine).get_table_names())
        for table, _, _ in _ADDITIVE_COLUMNS:
            if table not in actual_tables:
                raise ValueError(
                    f"migrations: registry references unknown table {table!r}; "
                    "fix _ADDITIVE_COLUMNS in cardplatform.db.migrations"
                )

        existing = {table: _existing_columns(conn, table) for table, _, _ in _ADDITIVE_COLUMNS}
        for table, column, sqlite_type in _ADDITIVE_COLUMNS:
            if column in existing.get(table, set()):
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_type}"))
                logger.info("migrations: added column %s.%s", table, column)
            except OperationalError as exc:
                # Transient (locked DB, disk full): log and continue so the next
                # startup retries rather than hard-failing the whole migration.
                logger.warning("migrations: failed to add %s.%s: %s", table, column, exc)
