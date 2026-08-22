import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cardplatform.api import create_app, get_scan_store, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.scans.store import ScanStore


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 82), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded, tmp_path):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_scan_store] = lambda: ScanStore(
        seeded, Settings(data_dir=tmp_path)
    )
    return TestClient(app)


def _record(client, status="confident", predicted="base1-4", **extra):
    params = {"status": status, "confidence": 0.97}
    if predicted is not None:
        params["predicted_card_id"] = predicted
    params.update(extra)
    return client.post("/scans", params=params, files={"file": ("scan.png", _png(), "image/png")})


def test_recording_a_scan_returns_its_id(client):
    response = _record(client)

    assert response.status_code == 201
    assert isinstance(response.json()["id"], int)
    assert response.json()["confirmed"] is False


def test_record_scan_persists_rectified_path_and_variant(client):
    """Phase 3b: the recognize endpoint surfaces rectified_path; the frontend passes
    it and the request variant back through /scans, and they land on the row."""
    response = _record(
        client, rectified_path="rectified/abc.png", variant="normal"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rectified_path"] == "rectified/abc.png"
    assert body["variant"] == "normal"


def test_record_scan_defaults_rectified_path_and_variant_to_none(client):
    """Omitting the new params keeps existing behaviour: nulls, not errors."""
    body = _record(client).json()

    assert body["rectified_path"] is None
    assert body["variant"] is None


def test_record_scan_persists_batch_id_and_index(client):
    """Phase 4: the bulk cataloger posts one card at a time, each carrying the
    batch_id from /recognize/batch and its own slot index. Both must reach the
    row — they were declared on the client but not on the route, so FastAPI
    dropped them silently."""
    body = _record(client, batch_id="batch-1", batch_index=2).json()

    assert body["batch_id"] == "batch-1"
    assert body["batch_index"] == 2


def test_record_scan_defaults_batch_id_and_index_to_none(client):
    """A single-card scan is a singleton batch: NULL, not an error."""
    body = _record(client).json()

    assert body["batch_id"] is None
    assert body["batch_index"] is None


def test_accuracy_counts_one_bulk_photo_once(client):
    """THE point of batch grouping. Nine cards off one binder page are one
    photograph's worth of evidence. Before the route accepted batch_id every
    bulk card landed as its own singleton batch and inflated the baseline —
    3 cards here would have read total == 4 instead of 2."""
    for i in range(3):
        _record(client, batch_id="batch-1", batch_index=i)
    _record(client)  # a genuine single-card scan

    body = client.get("/scans/accuracy").json()

    assert body["total"] == 2  # 1 batch + 1 singleton, NOT 4


def test_a_not_found_scan_can_be_recorded_without_a_card(client):
    """These are the interesting failures — they must be loggable."""
    response = _record(client, status="not_found", predicted=None)

    assert response.status_code == 201
    assert response.json()["predicted_card_id"] is None


def test_confirming_a_scan_marks_it_correct(client):
    scan_id = _record(client).json()["id"]

    response = client.post(f"/scans/{scan_id}/confirm")

    assert response.status_code == 200
    assert response.json()["confirmed"] is True
    assert response.json()["corrected_card_id"] is None


def test_correcting_a_scan_records_the_real_card(client):
    scan_id = _record(client).json()["id"]

    response = client.post(f"/scans/{scan_id}/correct", params={"card_id": "base4-4"})

    assert response.status_code == 200
    assert response.json()["corrected_card_id"] == "base4-4"
    assert response.json()["confirmed"] is True


def test_correcting_to_an_unknown_card_is_404(client):
    scan_id = _record(client).json()["id"]

    assert client.post(f"/scans/{scan_id}/correct", params={"card_id": "nope-1"}).status_code == 404


def test_correcting_a_missing_scan_is_404(client):
    assert client.post("/scans/9999/correct", params={"card_id": "base1-4"}).status_code == 404


def test_confirming_a_missing_scan_is_404(client):
    assert client.post("/scans/9999/confirm").status_code == 404


def test_accuracy_endpoint_reports_precision_and_coverage(client):
    right = _record(client).json()["id"]
    wrong = _record(client).json()["id"]
    _record(client, status="not_found", predicted=None)

    client.post(f"/scans/{right}/confirm")
    client.post(f"/scans/{wrong}/correct", params={"card_id": "base4-4"})

    body = client.get("/scans/accuracy").json()
    assert body["total"] == 3
    assert body["answered"] == 2
    assert body["predicted"] == 2
    assert body["correct"] == 1
    assert body["precision"] == 0.5
    assert body["coverage"] == pytest.approx(2 / 3)
    assert body["by_status"]["not_found"] == 1


def test_accuracy_route_is_not_shadowed_by_the_id_route(client):
    """/scans/accuracy must not be parsed as /scans/{scan_id}."""
    assert client.get("/scans/accuracy").status_code == 200


def test_recent_scans_are_listed_newest_first(client):
    _record(client, predicted="base1-4")
    _record(client, predicted="base4-4")

    body = client.get("/scans").json()

    assert len(body) == 2
    assert body[0]["predicted_card_id"] == "base4-4"
