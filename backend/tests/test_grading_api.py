"""T3: grading-label HTTP endpoints over the GradingLabelStore.

The endpoint is the only way a user records a known grade, so these tests pin
the honest-data contract at the boundary: card_id/variant come from the scan
(not the body), unknown scan is 404, bad grade/grader or a no-card scan is 400,
and the list endpoint returns [] rather than 404 when nothing is graded yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_scan_store, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, ScanLog
from cardplatform.scans.store import ScanStore


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


def test_post_creates_a_label(client, seeded):
    scan = _scan(seeded, variant="holofoil")

    response = client.post(
        f"/scans/{scan.id}/grade-label",
        json={"grade": 9.0, "grader": "PSA", "cert_number": "111", "notes": "pop 1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["scan_id"] == scan.id
    assert body["card_id"] == "base1-4"
    assert body["variant"] == "holofoil"
    assert body["grade"] == 9.0
    assert body["grader"] == "PSA"
    assert body["cert_number"] == "111"
    assert body["notes"] == "pop 1"
    assert body["created_at"] is not None


def test_post_resolves_card_id_from_the_scan_not_the_body(client, seeded):
    """The body carries no card_id; the store takes it from corrected > predicted."""
    scan = _scan(seeded, predicted="base1-4", corrected="base4-4")

    body = client.post(
        f"/scans/{scan.id}/grade-label",
        json={"grade": 8.0, "grader": "BGS"},
    ).json()

    assert body["card_id"] == "base4-4"


def test_post_returns_none_variant_when_scan_has_none(client, seeded):
    """No variant on the scan surfaces as null, never a fabricated 'normal'."""
    scan = _scan(seeded, variant=None)

    body = client.post(
        f"/scans/{scan.id}/grade-label",
        json={"grade": 9.0, "grader": "PSA"},
    ).json()

    assert body["variant"] is None


def test_post_upserts_one_label_per_scan(client, seeded):
    scan = _scan(seeded)

    first = client.post(
        f"/scans/{scan.id}/grade-label", json={"grade": 8.0, "grader": "PSA"}
    )
    second = client.post(
        f"/scans/{scan.id}/grade-label",
        json={"grade": 9.0, "grader": "CGC", "cert_number": "222"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["grade"] == 9.0
    assert second.json()["grader"] == "CGC"

    # The list confirms there is exactly one row for this scan.
    labels = client.get("/grading/labels").json()
    assert len(labels) == 1


def test_post_404_for_unknown_scan(client):
    response = client.post(
        "/scans/9999/grade-label", json={"grade": 9.0, "grader": "PSA"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "scan not found"


def test_post_400_for_bad_grade(client, seeded):
    scan = _scan(seeded)
    response = client.post(
        f"/scans/{scan.id}/grade-label", json={"grade": 10.5, "grader": "PSA"}
    )
    assert response.status_code == 400
    assert "out of range" in response.json()["detail"]


def test_post_400_for_unknown_grader(client, seeded):
    scan = _scan(seeded)
    response = client.post(
        f"/scans/{scan.id}/grade-label", json={"grade": 9.0, "grader": "PSAX"}
    )
    assert response.status_code == 400
    assert "grader" in response.json()["detail"]


def test_post_400_for_a_scan_with_no_card(client, seeded):
    scan = _scan(seeded, predicted=None)
    response = client.post(
        f"/scans/{scan.id}/grade-label", json={"grade": 9.0, "grader": "PSA"}
    )
    assert response.status_code == 400
    assert "no card" in response.json()["detail"]


def test_get_one_returns_the_label(client, seeded):
    scan = _scan(seeded)
    client.post(
        f"/scans/{scan.id}/grade-label", json={"grade": 9.0, "grader": "PSA"}
    )

    body = client.get(f"/scans/{scan.id}/grade-label").json()
    assert body["scan_id"] == scan.id
    assert body["grade"] == 9.0


def test_get_one_404_when_no_label(client, seeded):
    scan = _scan(seeded)
    assert client.get(f"/scans/{scan.id}/grade-label").status_code == 404


def test_list_returns_empty_when_none(client):
    assert client.get("/grading/labels").json() == []


def test_list_returns_newest_first(client, seeded):
    a = _scan(seeded)
    b = _scan(seeded)
    c = _scan(seeded)
    client.post(f"/scans/{a.id}/grade-label", json={"grade": 8.0, "grader": "PSA"})
    client.post(f"/scans/{b.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})
    client.post(f"/scans/{c.id}/grade-label", json={"grade": 7.0, "grader": "PSA"})

    body = client.get("/grading/labels").json()
    assert [r["scan_id"] for r in body] == [c.id, b.id, a.id]


def test_list_filters_by_card_id(client, seeded):
    a = _scan(seeded, predicted="base1-4")
    b = _scan(seeded, predicted="base4-4")
    client.post(f"/scans/{a.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})
    client.post(f"/scans/{b.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})

    body = client.get("/grading/labels", params={"card_id": "base4-4"}).json()
    assert [r["card_id"] for r in body] == ["base4-4"]


def test_list_filters_by_grader_case_insensitively(client, seeded):
    a = _scan(seeded)
    b = _scan(seeded)
    client.post(f"/scans/{a.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})
    client.post(f"/scans/{b.id}/grade-label", json={"grade": 9.0, "grader": "CGC"})

    body = client.get("/grading/labels", params={"grader": "cgc"}).json()
    assert [r["grader"] for r in body] == ["CGC"]


def test_list_combines_filters(client, seeded):
    a = _scan(seeded, predicted="base1-4")
    b = _scan(seeded, predicted="base1-4")
    c = _scan(seeded, predicted="base4-4")
    client.post(f"/scans/{a.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})
    client.post(f"/scans/{b.id}/grade-label", json={"grade": 9.0, "grader": "CGC"})
    client.post(f"/scans/{c.id}/grade-label", json={"grade": 9.0, "grader": "PSA"})

    body = client.get(
        "/grading/labels", params={"card_id": "base1-4", "grader": "psa"}
    ).json()
    assert [r["scan_id"] for r in body] == [a.id]
