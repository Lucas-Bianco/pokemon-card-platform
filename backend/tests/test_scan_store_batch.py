"""Tests for batch scan logging (Phase 4)."""
from __future__ import annotations

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.scans.store import ScanStore


def _seed(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def _result(status="confident", card_id="base1-4", variant="normal"):
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    return RecognitionResult(
        card_id=card_id,
        confidence=0.9,
        status=status,
        candidates=(),
        ocr=OcrReading(),
        visual_margin=0.1,
        rectified_path="rectified/x.png",
    )


def test_record_batch_writes_one_photo_and_n_rows(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    results = [_result(), _result(card_id="base1-4"), _result(status="not_found", card_id=None)]
    scan_ids = store.record_batch(
        b"\x89PNG fake", "batch-1", results, variants=["normal", "normal", None]
    )
    assert len(scan_ids) == 3
    rows = store.recent(limit=10)
    batch_rows = sorted(rows[-3:], key=lambda r: r.id)
    # All rows share one source photo.
    assert len({r.image_path for r in batch_rows}) == 1
    # batch_id + batch_index stamped.
    assert [r.batch_id for r in batch_rows] == ["batch-1", "batch-1", "batch-1"]
    assert [r.batch_index for r in batch_rows] == [0, 1, 2]
    # not_found is logged too (ground truth).
    assert batch_rows[-1].status == "not_found"


def test_accuracy_is_batch_aware(db, tmp_path):
    """N rows per batch photo count ONCE in accuracy().total — don't inflate the baseline."""
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    store.record_batch(b"\x89PNG", "b1", [_result(), _result(), _result()])
    store.record(
        image_bytes=b"\x89PNG",
        status="confident",
        predicted_card_id="base1-4",
        variant="normal",
    )
    acc = store.accuracy()
    assert acc.total == 2  # 1 batch + 1 singleton, NOT 4


def test_record_singleton_has_null_batch_id(db, tmp_path):
    _seed(db)
    store = ScanStore(db, Settings(data_dir=tmp_path))
    scan = store.record(
        image_bytes=b"\x89PNG", status="confident", predicted_card_id="base1-4", variant="normal"
    )
    assert scan.batch_id is None
    assert scan.batch_index is None