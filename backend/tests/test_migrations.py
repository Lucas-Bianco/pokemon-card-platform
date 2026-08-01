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
    """GradingLabel mirrors the shape described in T1; scan_id is unique."""
    _seed_card(db)
    scan = ScanLog(image_path="scans/x.png", predicted_card_id="base1-4", status="confident")
    db.add(scan)
    db.commit()

    label = GradingLabel(
        scan_id=scan.id,
        card_id="base1-4",
        variant="holofoil",
        grade=9,
        grader="PSA",
        cert_number="12345678",
        notes="off-center left",
    )
    db.add(label)
    db.commit()
    db.expunge_all()

    got = db.query(GradingLabel).one()
    assert got.grade == 9
    assert got.grader == "PSA"
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
        card_id="base1-4", grader="PSA", grade=9, variant="holofoil", source="pkmnprices"
    )
    db.add(snap)
    db.commit()
    db.expunge_all()

    got = db.query(GradedPriceSnapshot).filter_by(card_id="base1-4").one()
    assert got.fetched_at.tzinfo is not None