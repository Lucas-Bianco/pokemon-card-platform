"""Tests for POST /recognize/batch (Phase 4)."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_recognition_service, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.recognition import service as svc

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def _png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1200, 1500), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            image_small="https://images.example/base1-4/small.png",
            image_large="https://images.example/base1-4/large.png",
        )
    )
    db.commit()
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="normal",
            low=600.0,
            mid=750.0,
            high=1200.0,
            market=800.43,
            source_updated_at="2026/07/29",
            fetched_at=NOW,
        )
    )
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    # A lightweight service: recognize_many is monkeypatched per-test on the
    # class, so the real CLIP/FAISS stack (get_recognition_stack) is never
    # loaded and no index needs to exist on disk.
    app.dependency_overrides[get_recognition_service] = lambda: svc.RecognitionService(
        session=seeded, encoder=None, index=None, reader=None
    )
    return TestClient(app)


def test_recognize_batch_returns_n_results(client, monkeypatch):
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    fake_quads = [object(), object()]
    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads",
                        lambda img: [("otsu_rect", q) for q in fake_quads])

    def fake_many(self, img, quads):
        return [(q, RecognitionResult(card_id="base1-4", confidence=0.9, status="confident",
                                      candidates=(), ocr=OcrReading(), visual_margin=0.1,
                                      rectified_path="rectified/a.png"), None) for q in quads]
    monkeypatch.setattr(svc.RecognitionService, "recognize_many", fake_many)

    resp = client.post("/recognize/batch",
                       files={"file": ("page.png", _png_bytes(), "image/png")},
                       params={"variant": "normal", "max_cards": 9})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert len(body["results"]) == 2
    assert all(r["status"] == "confident" for r in body["results"])
    assert "batch_id" in body and body["batch_id"]


def test_recognize_batch_honest_none_price_for_not_found(client, monkeypatch):
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads",
                        lambda img: [("otsu_rect", object())])
    monkeypatch.setattr(svc.RecognitionService, "recognize_many",
                        lambda self, img, quads: [(q, RecognitionResult(
                            card_id=None, confidence=0.0, status="not_found", candidates=(),
                            ocr=OcrReading(), visual_margin=0.0, rectified_path=None), None)
                            for q in quads])
    resp = client.post("/recognize/batch", files={"file": ("p.png", _png_bytes(), "image/png")})
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["status"] == "not_found"
    assert body["results"][0]["card"] is None
    assert body["results"][0]["price"] is None  # never $0


def test_recognize_batch_max_cards_clamp(client, monkeypatch):
    from cardplatform.recognition.types import RecognitionResult, OcrReading

    monkeypatch.setattr("cardplatform.recognition.detectors.detect_all_quads",
                        lambda img: [("otsu_rect", object()) for _ in range(5)])
    monkeypatch.setattr(svc.RecognitionService, "recognize_many",
                        lambda self, img, quads: [(q, RecognitionResult(
                            card_id="base1-4", confidence=0.9, status="confident", candidates=(),
                            ocr=OcrReading(), visual_margin=0.1, rectified_path=None), None)
                            for q in quads])
    resp = client.post("/recognize/batch",
                       files={"file": ("p.png", _png_bytes(), "image/png")},
                       params={"max_cards": 2})
    assert resp.json()["count"] == 2


def test_recognize_batch_max_cards_out_of_range_422(client, monkeypatch):
    resp = client.post("/recognize/batch",
                       files={"file": ("p.png", _png_bytes(), "image/png")},
                       params={"max_cards": 99})
    assert resp.status_code == 422