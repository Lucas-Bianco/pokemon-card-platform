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

from cardplatform.db.models import GradingLabel

logger = logging.getLogger(__name__)

# Registry of additive column migrations. Append here in future tasks. Each
# entry is (table, column, sqlite_type). Columns are nullable, no NOT NULL, no
# default.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("scan_logs", "rectified_path", "VARCHAR"),
    ("scan_logs", "variant", "VARCHAR"),
    ("scan_logs", "batch_id", "VARCHAR"),
    ("scan_logs", "batch_index", "INTEGER"),
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

        _ensure_grading_labels_variant_nullable(conn, actual_tables)


def _ensure_grading_labels_variant_nullable(conn, actual_tables: set[str]) -> None:
    """One-time fix-up for T1's `grading_labels.variant` NOT NULL column.

    T3 stores None there: a scan that never picked a variant is honestly
    unlabelled, not a fabricated "normal". T1 created the column NOT NULL, and
    SQLite cannot ALTER COLUMN, so on DBs that already built the table NOT NULL
    we rebuild it from the (now-nullable) model. Safe only because the table is
    empty until T3's endpoint populates it — a non-empty table is left untouched
    and logged rather than risk dropping real labels.
    """
    if "grading_labels" not in actual_tables:
        # create_all will build it nullable from the current model on this start.
        return
    info = conn.execute(text("PRAGMA table_info(grading_labels)")).fetchall()
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
    variant_row = next((r for r in info if r[1] == "variant"), None)
    if variant_row is None or not variant_row[3]:
        return  # already nullable (or absent, which create_all will handle)
    count = conn.execute(text("SELECT COUNT(*) FROM grading_labels")).scalar()
    if count:
        logger.warning(
            "migrations: grading_labels.variant is NOT NULL with %d rows; "
            "leaving as-is to avoid dropping labels",
            count,
        )
        return
    conn.execute(text("DROP TABLE grading_labels"))
    GradingLabel.__table__.create(conn)
    logger.info("migrations: rebuilt empty grading_labels with nullable variant")
