"""Phase 3b T1: idempotent migration helper + new grading tables.

These tests pin the contract that lets a project with NO Alembic evolve an
existing populated DB: `run_migrations` only ADDs nullable columns to existing
tables (never NOT NULL, never a default), and `Database.create_all()` now both
creates new tables (via Base.metadata.create_all) and ALTERs existing ones (via
run_migrations). The migration must be safe to run repeatedly and on a fresh DB.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import inspect, text

from cardplatform.config import Settings
from cardplatform.db.migrations import run_migrations
from cardplatform.db.models import (
    Card,
    CardSet,
    GradedPriceSnapshot,
    GradingLabel,
    ScanLog,
)
from cardplatform.db.session import Database


def _columns(engine, table: str) -> set[str]:
    return {row["name"] for row in inspect(engine).get_columns(table)}


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _seed_card(db) -> None:
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def test_run_migrations_adds_scan_logs_columns_when_absent(tmp_path):
    """A fresh DB built without the new columns must gain them on migration."""
    settings = Settings(data_dir=tmp_path)
    database = Database(settings)
    # Create only the base schema, then DROP the two new columns to simulate the
    # pre-3b shape. We can't easily build the "old" schema from scratch without
    # the new columns (create_all always adds them now), so drop them post-hoc.
    from cardplatform.db.models import Base

    Base.metadata.create_all(database.engine)
    with database.engine.begin() as conn:
        conn.execute(text("ALTER TABLE scan_logs DROP COLUMN rectified_path"))
        conn.execute(text("ALTER TABLE scan_logs DROP COLUMN variant"))
    assert "rectified_path" not in _columns(database.engine, "scan_logs")
    assert "variant" not in _columns(database.engine, "scan_logs")

    run_migrations(database.engine)

    cols = _columns(database.engine, "scan_logs")
    assert "rectified_path" in cols
    assert "variant" in cols


def test_run_migrations_is_idempotent(tmp_path):
    """Running twice must not error and must leave the columns present."""
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()  # already adds the columns
    before = _columns(database.engine, "scan_logs")

    run_migrations(database.engine)
    run_migrations(database.engine)

    assert _columns(database.engine, "scan_logs") == before


def test_run_migrations_logs_additions_at_info(caplog, tmp_path):
    database = Database(Settings(data_dir=tmp_path))
    from cardplatform.db.models import Base

    Base.metadata.create_all(database.engine)
    with database.engine.begin() as conn:
        conn.execute(text("ALTER TABLE scan_logs DROP COLUMN rectified_path"))

    with caplog.at_level(logging.INFO, logger="cardplatform.db.migrations"):
        run_migrations(database.engine)
    assert any("rectified_path" in rec.message for rec in caplog.records)


def test_create_all_creates_the_two_new_tables(tmp_path):
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()
    tables = _tables(database.engine)
    assert "grading_labels" in tables
    assert "graded_price_snapshots" in tables


def test_create_all_then_re_migrate_leaves_existing_rows_untouched(tmp_path):
    """Re-running migrations on a populated DB must not touch row counts."""
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()
    with database.session() as s:
        _seed_card(s)
        s.add(ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident"))
        s.commit()

    with database.session() as s:
        before = s.query(ScanLog).count()

    # Re-run via create_all (which now migrates) and directly; both no-op.
    database.create_all()
    run_migrations(database.engine)

    with database.session() as s:
        after = s.query(ScanLog).count()
    assert before == after


def test_scan_log_new_columns_are_nullable(tmp_path):
    """Existing rows get NULL; new rows may omit the columns."""
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()
    with database.session() as s:
        _seed_card(s)
        s.add(ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident"))
        s.commit()

    with database.session() as s:
        row = s.query(ScanLog).one()
        assert row.rectified_path is None
        assert row.variant is None


def test_grading_label_persists_and_enforces_one_per_scan(db):
    """GradingLabel mirrors the shape described in T1; scan_id is unique.

    Uses a .5 grade to verify the Float column supports BGS/CGC half-grades.
    """
    _seed_card(db)
    scan = ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident")
    db.add(scan)
    db.commit()

    label = GradingLabel(
        scan_id=scan.id,
        card_id="base1-4",
        variant="holofoil",
        grade=9.5,
        grader="CGC",
        cert_number="12345678",
        notes="off-center left",
    )
    db.add(label)
    db.commit()
    db.expunge_all()

    got = db.query(GradingLabel).one()
    assert got.grade == 9.5
    assert got.grader == "CGC"
    assert got.cert_number == "12345678"
    assert got.created_at.tzinfo is not None


def test_grading_label_rejects_a_second_label_for_the_same_scan(db):
    from sqlalchemy.exc import IntegrityError

    _seed_card(db)
    scan = ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident")
    db.add(scan)
    db.commit()

    db.add(
        GradingLabel(scan_id=scan.id, card_id="base1-4", variant="holofoil", grade=9, grader="PSA")
    )
    db.commit()
    db.add(
        GradingLabel(scan_id=scan.id, card_id="base1-4", variant="holofoil", grade=10, grader="CGC")
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_graded_snapshot_duplicate_is_rejected_by_unique_constraint(db):
    """Mirror of test_duplicate_snapshot_is_rejected_by_unique_constraint."""
    from sqlalchemy.exc import IntegrityError

    _seed_card(db)
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=9,
            variant="holofoil",
            source="pkmnprices",
            source_updated_at="2024/01/01",
        )
    )
    db.commit()

    db.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=9,
            variant="holofoil",
            source="pkmnprices",
            source_updated_at="2024/01/01",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_graded_snapshot_missing_source_updated_at_also_dedupe(db):
    """The '' sentinel must collide, unlike NULL (same guard as PriceSnapshot)."""
    from sqlalchemy.exc import IntegrityError

    _seed_card(db)
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4", grader="PSA", grade=9, variant="holofoil", source="pkmnprices"
        )
    )
    db.commit()
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4", grader="PSA", grade=9, variant="holofoil", source="pkmnprices"
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_graded_snapshot_with_differing_timestamp_inserts_new_row(db):
    _seed_card(db)
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=9,
            variant="holofoil",
            source="pkmnprices",
            source_updated_at="2024/01/01",
        )
    )
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4",
            grader="PSA",
            grade=9,
            variant="holofoil",
            source="pkmnprices",
            source_updated_at="2024/01/02",
        )
    )
    db.commit()

    count = db.query(GradedPriceSnapshot).filter_by(card_id="base1-4").count()
    assert count == 2


def test_graded_snapshot_fetched_at_autopopulates_as_tzaware_utc(db):
    _seed_card(db)
    snap = GradedPriceSnapshot(
        card_id="base1-4", grader="PSA", grade=9.5, variant="holofoil", source="pkmnprices"
    )
    db.add(snap)
    db.commit()
    db.expunge_all()

    got = db.query(GradedPriceSnapshot).filter_by(card_id="base1-4").one()
    assert got.fetched_at.tzinfo is not None
    assert got.grade == 9.5


def test_graded_snapshot_accepts_half_grade(db):
    """A .5 grade (BGS/CGC) round-trips; PSA whole numbers also work."""
    _seed_card(db)
    db.add(
        GradedPriceSnapshot(
            card_id="base1-4", grader="BGS", grade=9.5, variant="holofoil", source="pkmnprices"
        )
    )
    db.commit()
    db.expunge_all()
    got = db.query(GradedPriceSnapshot).one()
    assert got.grade == 9.5


def test_run_migrations_raises_loudly_for_unknown_table(tmp_path, monkeypatch):
    """A typo'd table name in the registry must raise, not silently swallow.

    Regression guard: with a broad except, PRAGMA on a missing table returns an
    empty column set, the ALTER fails, and the warning is logged every startup
    while the column never appears — an invisible bug. The loud raise surfaces it.
    """
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()

    import cardplatform.db.migrations as m

    monkeypatch.setattr(
        m,
        "_ADDITIVE_COLUMNS",
        (("nonexistent_table_xyz", "some_col", "VARCHAR"),),
    )
    with pytest.raises(ValueError, match="unknown table 'nonexistent_table_xyz'"):
        run_migrations(database.engine)


def test_run_migrations_continues_after_a_transient_operational_error(tmp_path, monkeypatch):
    """An OperationalError on one ALTER is logged and the loop continues.

    The PRAGMA pre-check normally skips existing columns, so to reach the ALTER
    failure path we point the registry at a column that already exists ('id') and
    make the pre-check lie about that one column: the ALTER then fires and SQLite
    raises OperationalError 'duplicate column name', which the narrowed except
    swallows and logs while the rest of the run continues.
    """
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()
    # Drop variant so the good entry still has work to do after the failing one.
    from cardplatform.db.models import Base

    with database.engine.begin() as conn:
        conn.execute(text("ALTER TABLE scan_logs DROP COLUMN variant"))

    import cardplatform.db.migrations as m

    real_existing = m._existing_columns

    def fake_existing(conn, table):
        # Hide 'id' from the pre-check so the ALTER for it actually fires.
        cols = real_existing(conn, table)
        return cols - {"id"}

    monkeypatch.setattr(m, "_existing_columns", fake_existing)
    monkeypatch.setattr(
        m,
        "_ADDITIVE_COLUMNS",
        (
            ("scan_logs", "id", "INTEGER"),  # ALTER fires -> duplicate column -> OperationalError
            ("scan_logs", "variant", "VARCHAR"),  # still applies
        ),
    )

    run_migrations(database.engine)

    with database.engine.connect() as c:
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(scan_logs)")).fetchall()}
    assert "variant" in cols  # the loop continued past the swallowed error


# --- T3: grading_labels.variant nullable rebuild (see _ensure_grading_labels_nullable) ---

# The DDL T1 originally created `grading_labels` with: `variant VARCHAR NOT NULL`.
# Used below to simulate a DB built before T3 relaxed the column, so the rebuild
# migration has a NOT-NULL table to act on. Built by hand (not from the current
# model, which is nullable) so the test actually exercises the NOT-NULL branch.
_T1_GRADING_LABELS_DDL = """
CREATE TABLE grading_labels (
    id INTEGER NOT NULL,
    scan_id INTEGER NOT NULL,
    card_id VARCHAR NOT NULL,
    variant VARCHAR NOT NULL,
    grade FLOAT NOT NULL,
    grader VARCHAR NOT NULL,
    cert_number VARCHAR,
    notes VARCHAR,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (scan_id),
    FOREIGN KEY(scan_id) REFERENCES scan_logs (id),
    FOREIGN KEY(card_id) REFERENCES cards (id)
)
"""


def _variant_notnull(engine) -> bool:
    """True if grading_labels.variant still carries a NOT NULL constraint."""
    with engine.connect() as c:
        info = c.execute(text("PRAGMA table_info(grading_labels)")).fetchall()
    variant_row = next((r for r in info if r[1] == "variant"), None)
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    return bool(variant_row and variant_row[3])


def _reset_grading_labels_to_t1_shape(engine) -> None:
    """Drop the nullable table create_all made and rebuild it NOT NULL (T1 shape)."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE grading_labels"))
        conn.execute(text(_T1_GRADING_LABELS_DDL))


def test_grading_labels_rebuild_skips_a_non_empty_table(tmp_path, caplog):
    """The rebuild's whole safety story: a non-empty grading_labels table is
    never dropped/rebuilt, even when its variant column is NOT NULL.

    If this guard regressed, real user labels would be silently destroyed on the
    next startup. This test seeds one row into a T1-shaped (NOT NULL variant)
    table, runs the migration, and asserts the row survives, the column stays
    NOT NULL (i.e. the table was NOT rebuilt), and a warning was logged.
    """
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()  # builds grading_labels with the current nullable variant
    with database.session() as s:
        _seed_card(s)
        s.add(ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident"))
        s.commit()

    _reset_grading_labels_to_t1_shape(database.engine)
    assert _variant_notnull(database.engine) is True

    with database.engine.begin() as conn:
        # Insert a real label into the NOT-NULL table (variant required).
        conn.execute(
            text(
                "INSERT INTO grading_labels "
                "(scan_id, card_id, variant, grade, grader, created_at) "
                "VALUES (1, 'base1-4', 'holofoil', 9.0, 'PSA', '2026-01-01 00:00:00')"
            )
        )

    with caplog.at_level(logging.WARNING, logger="cardplatform.db.migrations"):
        run_migrations(database.engine)

    # The table was NOT rebuilt: row survives and variant is still NOT NULL.
    assert _variant_notnull(database.engine) is True
    with database.engine.connect() as c:
        count = c.execute(text("SELECT COUNT(*) FROM grading_labels")).scalar()
    assert count == 1
    assert any("leaving as-is" in rec.message for rec in caplog.records)


def test_grading_labels_rebuild_rebuilds_an_empty_table_to_nullable(tmp_path, caplog):
    """An empty NOT-NULL grading_labels table IS rebuilt to nullable (happy path).

    This is the case the migration exists for: a DB built under T1 (NOT NULL
    variant) with no labels yet. After run_migrations the column is nullable and
    the rebuild is logged at info.
    """
    database = Database(Settings(data_dir=tmp_path))
    database.create_all()
    with database.session() as s:
        _seed_card(s)
        s.add(ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident"))
        s.commit()  # scan_logs row id=1, so the NULL-variant insert below satisfies its FK

    _reset_grading_labels_to_t1_shape(database.engine)
    assert _variant_notnull(database.engine) is True

    with caplog.at_level(logging.INFO, logger="cardplatform.db.migrations"):
        run_migrations(database.engine)

    assert _variant_notnull(database.engine) is False
    assert any("rebuilt empty grading_labels" in rec.message for rec in caplog.records)
    # A nullable None variant can now be inserted (the point of the migration).
    with database.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO grading_labels "
                "(scan_id, card_id, variant, grade, grader, created_at) "
                "VALUES (1, 'base1-4', NULL, 9.0, 'PSA', '2026-01-01 00:00:00')"
            )
        )
