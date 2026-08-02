"""T3: GradingLabelStore — record a known grade against a scan.

These tests pin down the honest-data rules that make this label set worth
training a predictor on: one label per scan, card_id resolved from the user's
correction (never fabricated), variant taken from the scan (never defaulted),
and grade/grader validated.
"""

from __future__ import annotations

import pytest

from cardplatform.config import Settings  # noqa: F401  (mirrors sibling tests' imports)
from cardplatform.db.models import Card, CardSet, GradingLabel, ScanLog
from cardplatform.grading.store import GradingLabelStore


def _seed(db) -> None:
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def _scan(db, predicted="base1-4", corrected=None, variant=None) -> ScanLog:
    scan = ScanLog(
        image_path="scans/x.png",
        predicted_card_id=predicted,
        corrected_card_id=corrected,
        status="confident",
        variant=variant,
    )
    db.add(scan)
    db.commit()
    return scan


def test_label_inserts_one_row(db):
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    row = store.label(scan.id, grade=9.0, grader="PSA")

    assert row.id is not None
    assert row.scan_id == scan.id
    assert row.card_id == "base1-4"
    assert row.variant is None
    assert row.grade == 9.0
    assert row.grader == "PSA"
    assert row.cert_number is None
    assert row.notes is None
    assert row.created_at.tzinfo is not None
    assert db.query(GradingLabel).count() == 1


def test_label_uses_the_user_correction_over_the_prediction(db):
    """corrected_card_id is the user-confirmed truth and must win over predicted."""
    _seed(db)
    scan = _scan(db, predicted="base1-4", corrected="base4-4")
    store = GradingLabelStore(db)

    row = store.label(scan.id, grade=8.0, grader="BGS")

    assert row.card_id == "base4-4"


def test_label_carries_the_scan_variant_without_fabricating_one(db):
    """variant is whatever the scan recorded; None stays None, never 'normal'."""
    _seed(db)
    scan = _scan(db, variant="holofoil")
    store = GradingLabelStore(db)

    row = store.label(scan.id, grade=9.0, grader="PSA")
    assert row.variant == "holofoil"

    none_scan = _scan(db, variant=None)
    none_row = store.label(none_scan.id, grade=9.0, grader="PSA")
    assert none_row.variant is None


def test_label_upserts_one_label_per_scan(db):
    """Re-labeling a scan updates the existing row; it must not insert a second."""
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    first = store.label(scan.id, grade=8.0, grader="PSA", cert_number="111")
    second = store.label(scan.id, grade=9.0, grader="CGC", cert_number="222", notes="regraded")

    assert db.query(GradingLabel).count() == 1
    assert second.id == first.id  # same row
    assert second.grade == 9.0
    assert second.grader == "CGC"
    assert second.cert_number == "222"
    assert second.notes == "regraded"
    # created_at is not re-stamped on update.
    assert second.created_at == first.created_at


def test_label_returns_none_for_an_unknown_scan(db):
    _seed(db)
    assert GradingLabelStore(db).label(9999, grade=9.0, grader="PSA") is None


def test_label_rejects_a_scan_with_no_card(db):
    """A not_found scan that was never corrected names no card and cannot be graded."""
    _seed(db)
    scan = _scan(db, predicted=None)
    store = GradingLabelStore(db)

    with pytest.raises(ValueError, match="no card"):
        store.label(scan.id, grade=9.0, grader="PSA")


def test_label_rejects_an_out_of_range_grade(db):
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    with pytest.raises(ValueError, match="out of range"):
        store.label(scan.id, grade=10.5, grader="PSA")
    with pytest.raises(ValueError, match="out of range"):
        store.label(scan.id, grade=0.5, grader="PSA")


def test_label_accepts_half_step_grades(db):
    """BGS/CGC use .5 increments; the bounds are inclusive at 9.5 and 1.0."""
    _seed(db)
    scan_hi = _scan(db)
    scan_lo = _scan(db)
    store = GradingLabelStore(db)

    assert store.label(scan_hi.id, grade=9.5, grader="BGS").grade == 9.5
    assert store.label(scan_lo.id, grade=1.0, grader="BGS").grade == 1.0


def test_label_uppercases_and_validates_the_grader(db):
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    assert store.label(scan.id, grade=9.0, grader="psa").grader == "PSA"

    with pytest.raises(ValueError, match="unknown grader"):
        store.label(scan.id, grade=9.0, grader="PSAX")


def test_label_persists_optional_fields(db):
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    row = store.label(
        scan.id, grade=9.0, grader="PSA", cert_number="999-42", notes="clean pop"
    )
    assert row.cert_number == "999-42"
    assert row.notes == "clean pop"


def test_for_scan_returns_the_label_or_none(db):
    _seed(db)
    scan = _scan(db)
    store = GradingLabelStore(db)

    assert store.for_scan(scan.id) is None
    store.label(scan.id, grade=9.0, grader="PSA")
    assert store.for_scan(scan.id).grade == 9.0
    assert store.for_scan(9999) is None


def test_list_labels_returns_newest_first(db):
    _seed(db)
    s1 = _scan(db)
    s2 = _scan(db)
    s3 = _scan(db)
    store = GradingLabelStore(db)

    store.label(s1.id, grade=8.0, grader="PSA")
    store.label(s2.id, grade=9.0, grader="PSA")
    store.label(s3.id, grade=7.0, grader="PSA")

    rows = store.list_labels()
    assert [r.scan_id for r in rows] == [s3.id, s2.id, s1.id]


def test_list_labels_filters_by_card_id(db):
    _seed(db)
    a = _scan(db, predicted="base1-4")
    b = _scan(db, predicted="base4-4")
    store = GradingLabelStore(db)

    store.label(a.id, grade=9.0, grader="PSA")
    store.label(b.id, grade=8.0, grader="PSA")

    rows = store.list_labels(card_id="base4-4")
    assert [r.card_id for r in rows] == ["base4-4"]


def test_list_labels_filters_by_grader_case_insensitively(db):
    _seed(db)
    a = _scan(db)
    b = _scan(db)
    c = _scan(db)
    store = GradingLabelStore(db)

    store.label(a.id, grade=9.0, grader="PSA")
    store.label(b.id, grade=9.0, grader="CGC")
    store.label(c.id, grade=9.0, grader="BGS")

    rows = store.list_labels(grader="cgc")
    assert [r.grader for r in rows] == ["CGC"]


def test_list_labels_combines_filters(db):
    _seed(db)
    a = _scan(db, predicted="base1-4")
    b = _scan(db, predicted="base1-4")
    c = _scan(db, predicted="base4-4")
    store = GradingLabelStore(db)

    store.label(a.id, grade=9.0, grader="PSA")
    store.label(b.id, grade=9.0, grader="CGC")
    store.label(c.id, grade=9.0, grader="PSA")

    rows = store.list_labels(card_id="base1-4", grader="psa")
    assert [r.scan_id for r in rows] == [a.id]


def test_list_labels_empty_when_no_match(db):
    _seed(db)
    assert GradingLabelStore(db).list_labels() == []
