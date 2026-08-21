"""Tests for GET /scans/{scan_id}/authenticity.

The endpoint surfaces the one honest auto-signal (printed number vs catalog) and
the user-driven checklist. It must resolve the card from the scan honestly
(corrected_card_id over predicted_card_id), 404 an unknown scan, and return an
honest no_card consistency result — not a 404 — when the scan named no card,
because the checklist still applies.
"""

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
    db.add(CardSet(id="sv9", name="Scarlet & Violet", series="SV"))
    # A holo card whose catalog number is "35".
    db.add(
        Card(
            id="sv9-35",
            set_id="sv9",
            name="Sprigatito",
            number="35",
            rarity="Rare Holo",
        )
    )
    # A non-holo card with number "80".
    db.add(
        Card(id="sv9-80", set_id="sv9", name="Floragato", number="80", rarity="Common")
    )
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


def _record(client, *, predicted, ocr=None, corrected=None, status="confident"):
    params = {"status": status, "confidence": 0.97}
    if predicted is not None:
        params["predicted_card_id"] = predicted
    if ocr is not None:
        params["collector_number_read"] = ocr
    scan_id = client.post(
        "/scans", params=params, files={"file": ("scan.png", _png(), "image/png")}
    ).json()["id"]
    if corrected is not None:
        client.post(f"/scans/{scan_id}/correct", params={"card_id": corrected})
    return scan_id


# --- shape ------------------------------------------------------------------


def test_authenticity_returns_consistency_and_checklist(client):
    scan_id = _record(client, predicted="sv9-35", ocr="035")
    r = client.get(f"/scans/{scan_id}/authenticity")
    assert r.status_code == 200
    body = r.json()
    assert "caveat" in body and body["caveat"]
    assert body["consistency"]["match"] == "match"
    assert body["consistency"]["card_name"] == "Sprigatito"
    assert isinstance(body["checklist"], list) and len(body["checklist"]) >= 4
    ids = {i["id"] for i in body["checklist"]}
    assert "rosette" in ids


# --- consistency cases ------------------------------------------------------


def test_authenticity_match_normalizes_padded_ocr(client):
    scan_id = _record(client, predicted="sv9-35", ocr="035")
    body = client.get(f"/scans/{scan_id}/authenticity").json()
    assert body["consistency"]["match"] == "match"
    assert body["consistency"]["printed_number"] == "35"
    assert body["consistency"]["catalog_number"] == "35"


def test_authenticity_mismatch_surfaces_honest_ambiguity(client):
    # The real baseline case: matched sv9-35 but OCR read "043".
    scan_id = _record(client, predicted="sv9-35", ocr="043")
    body = client.get(f"/scans/{scan_id}/authenticity").json()
    c = body["consistency"]
    assert c["match"] == "mismatch"
    assert c["printed_number"] == "43"
    assert c["catalog_number"] == "35"
    assert "cannot tell" in c["note"].lower()


def test_authenticity_unread_when_ocr_missing(client):
    scan_id = _record(client, predicted="sv9-35", ocr=None)
    body = client.get(f"/scans/{scan_id}/authenticity").json()
    assert body["consistency"]["match"] == "unread"
    assert body["consistency"]["printed_number"] is None
    assert body["consistency"]["catalog_number"] == "35"


def test_authenticity_no_card_when_scan_named_nothing(client):
    # A not_found scan: the checklist still applies (you may be inspecting a
    # card the pipeline failed to recognize), only the consistency says no_card.
    scan_id = _record(client, predicted=None, ocr="035", status="not_found")
    body = client.get(f"/scans/{scan_id}/authenticity").json()
    assert body["consistency"]["match"] == "no_card"
    assert body["consistency"]["card_id"] is None
    assert len(body["checklist"]) >= 4


def test_authenticity_uses_corrected_card_over_predicted(client):
    # The user corrected the prediction from sv9-80 to sv9-35. The consistency
    # check must use the corrected card (number 35), not the predicted (80).
    scan_id = _record(client, predicted="sv9-80", ocr="035", corrected="sv9-35")
    body = client.get(f"/scans/{scan_id}/authenticity").json()
    assert body["consistency"]["match"] == "match"
    assert body["consistency"]["card_name"] == "Sprigatito"
    assert body["consistency"]["catalog_number"] == "35"


# --- checklist gating -------------------------------------------------------


def test_authenticity_holo_rarity_enables_holo_check(client):
    scan_id = _record(client, predicted="sv9-35", ocr="035")
    items = client.get(f"/scans/{scan_id}/authenticity").json()["checklist"]
    holo = next(i for i in items if i["id"] == "holo_light")
    assert holo["applies"] is True


def test_authenticity_non_holo_rarity_disables_holo_check(client):
    scan_id = _record(client, predicted="sv9-80", ocr="080")
    items = client.get(f"/scans/{scan_id}/authenticity").json()["checklist"]
    holo = next(i for i in items if i["id"] == "holo_light")
    assert holo["applies"] is False


# --- errors -----------------------------------------------------------------


def test_authenticity_404_unknown_scan(client):
    r = client.get("/scans/999999/authenticity")
    assert r.status_code == 404