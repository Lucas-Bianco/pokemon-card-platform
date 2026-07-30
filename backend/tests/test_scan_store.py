from cardplatform.db.models import Card, CardSet, ScanLog


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
    import pytest
    from sqlalchemy.exc import IntegrityError

    _seed(db)
    db.add(ScanLog(image_path="scans/y.png", predicted_card_id="ghost-1", status="confident"))

    with pytest.raises(IntegrityError):
        db.commit()
