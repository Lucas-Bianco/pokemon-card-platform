import io

import pytest
from PIL import Image

from sqlalchemy.exc import IntegrityError

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, ScanLog
from cardplatform.scans.store import ScanStore


def _seed(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def test_scan_log_persists_a_prediction(db):
    _seed(db)
    db.add(
        ScanLog(
            image_path="scans/abc.png",
            predicted_card_id="base1-4",
            status="confident",
            confidence=0.97,
            visual_margin=0.14,
            collector_number_read="4",
        )
    )
    db.commit()

    row = db.query(ScanLog).one()
    assert row.predicted_card_id == "base1-4"
    assert row.corrected_card_id is None
    assert row.confirmed is False
    assert row.created_at.tzinfo is not None


def test_scan_log_accepts_a_correction(db):
    _seed(db)
    scan = ScanLog(image_path="scans/abc.png", predicted_card_id="base1-4", status="confident")
    db.add(scan)
    db.commit()

    scan.corrected_card_id = "base4-4"
    db.commit()

    assert db.query(ScanLog).one().corrected_card_id == "base4-4"


def test_scan_log_allows_a_prediction_of_nothing(db):
    """A not_found scan is still worth logging — those are the interesting failures."""
    _seed(db)
    db.add(ScanLog(image_path="scans/x.png", predicted_card_id=None, status="not_found"))
    db.commit()

    assert db.query(ScanLog).one().predicted_card_id is None


def test_scan_log_rejects_an_unknown_predicted_card(db):
    """predicted_card_id is a real foreign key; foreign keys are enforced in tests."""
    _seed(db)
    db.add(ScanLog(image_path="scans/y.png", predicted_card_id="ghost-1", status="confident"))

    with pytest.raises(IntegrityError):
        db.commit()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 82), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


def test_settings_expose_scan_dir(tmp_path):
    assert Settings(data_dir=tmp_path).scan_image_dir == tmp_path / "scans"


def test_record_writes_the_image_and_the_row(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))

    scan = store.record(
        image_bytes=_png(),
        predicted_card_id="base1-4",
        status="confident",
        confidence=0.97,
        visual_margin=0.14,
        collector_number_read="4",
    )

    assert scan.id is not None
    saved = tmp_path / scan.image_path
    assert saved.exists()
    assert Image.open(saved).size == (60, 82)


def test_recorded_image_paths_are_unique(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))

    first = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    second = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    assert first.image_path != second.image_path


def test_confirm_marks_the_prediction_correct(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    store.confirm(scan.id)

    assert store.get(scan.id).confirmed is True
    assert store.get(scan.id).corrected_card_id is None


def test_correct_records_the_real_card(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="ambiguous")

    store.correct(scan.id, "base4-4")

    stored = store.get(scan.id)
    assert stored.corrected_card_id == "base4-4"
    assert stored.confirmed is True


def test_correcting_to_an_unknown_card_is_rejected(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    with pytest.raises(ValueError, match="unknown card"):
        store.correct(scan.id, "nope-1")


def test_confirming_a_missing_scan_returns_none(db, tmp_path):
    _seed(db)
    assert ScanStore(db, Settings(data_dir=tmp_path)).confirm(9999) is None


def test_recent_returns_newest_first(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    second = store.record(image_bytes=_png(), predicted_card_id="base4-4", status="confident")

    assert store.recent()[0].id == second.id


def test_precision_counts_only_scans_that_made_a_prediction(db, tmp_path):
    """An ambiguous scan made no claim, so it can be neither right nor wrong."""
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    right = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    wrong = store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    amb = store.record(image_bytes=_png(), predicted_card_id=None, status="ambiguous")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    store.confirm(right.id)
    store.correct(wrong.id, "base4-4")
    store.correct(amb.id, "base4-4")

    stats = store.accuracy()
    assert stats.predicted == 2
    assert stats.correct == 1
    assert stats.precision == pytest.approx(0.5)


def test_coverage_is_answers_over_all_scans(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    store.record(image_bytes=_png(), predicted_card_id=None, status="ambiguous")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    stats = store.accuracy()
    assert stats.total == 4
    assert stats.answered == 1
    assert stats.coverage == pytest.approx(0.25)


def test_unreviewed_predictions_are_not_evidence(db, tmp_path):
    """A prediction nobody checked is neither right nor wrong."""
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")

    stats = store.accuracy()
    assert stats.answered == 1
    assert stats.predicted == 0
    assert stats.precision == 0.0


def test_status_breakdown_is_reported(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record(image_bytes=_png(), predicted_card_id="base1-4", status="confident")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")
    store.record(image_bytes=_png(), predicted_card_id=None, status="not_found")

    assert store.accuracy().by_status == {"confident": 1, "not_found": 2}


def test_precision_with_nothing_predicted_is_zero_not_a_crash(db, tmp_path):
    _seed(db)
    stats = ScanStore(db, Settings(data_dir=tmp_path)).accuracy()

    assert stats.predicted == 0
    assert stats.precision == 0.0
    assert stats.coverage == 0.0
    assert stats.by_status == {}
