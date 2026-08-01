"""Idempotent schema migrations for the no-Alembic project.

This project has no Alembic: `Base.metadata.create_all()` creates new tables at
startup but never ALTERs existing ones, so a populated DB cannot gain columns.
`run_migrations` fills that gap with `ALTER TABLE ... ADD COLUMN` statements that
are checked against `PRAGMA table_info` before running, so each is a no-op once
applied. New tables do NOT belong here (create_all handles them); only ALTERs to
existing tables.

Every addition is nullable with no default: a NOT NULL column added to a
non-empty table would fail mid-migration and leave the DB half-migrated. Each
statement is wrapped in its own try/except so a partial run is recoverable.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

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
    every column. Each ALTER is isolated so one failure does not abort the rest.
    """
    with engine.begin() as conn:
        existing = {table: _existing_columns(conn, table) for table, _, _ in _ADDITIVE_COLUMNS}
        for table, column, sqlite_type in _ADDITIVE_COLUMNS:
            if column in existing.get(table, set()):
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_type}"))
                logger.info("migrations: added column %s.%s", table, column)
            except Exception as exc:  # noqa: BLE001
                # A partial run must be recoverable: log and continue so the next
                # startup retries rather than hard-failing the whole migration.
                logger.warning("migrations: failed to add %s.%s: %s", table, column, exc)