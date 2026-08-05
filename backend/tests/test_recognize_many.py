"""Tests for recognize_many (Phase 4 batched recognition)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.recognition.service import RecognitionService
from cardplatform.recognition.types import Candidate, OcrReading


def _crop(w: int = 600, h: int = 825) -> Image.Image:
    return Image.new("RGB", (w, h), (200, 200, 200))


# --- fakes: aligned field names/constructor to the REAL ones in test_recognition_service.py ---


class _FakeIndex:
    """Returns a fixed candidate list per search, matching the real FakeIndex contract."""

    def __init__(self, card_id: str = "base1-4", score: float = 0.95):
        self._candidates = (
            [Candidate(card_id=card_id, visual_score=score)] if score >= 0.0 else []
        )

    def search(self, vec, top_k):
        return list(self._candidates)[:top_k]


class _FakeEncoder:
    dimension = 512

    def embed(self, image):
        return self.embed_many([image])[0]

    def embed_many(self, images, batch_size=128):
        return np.zeros((len(images), self.dimension), dtype=np.float32)


class _FakeReader:
    def __init__(self):
        self.read_images = []

    def read(self, crop):
        self.read_images.append(crop)
        return OcrReading()


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def _service(seeded, tmp_path, index):
    return RecognitionService(
        session=seeded,
        encoder=_FakeEncoder(),
        index=index,
        reader=_FakeReader(),
        settings=Settings(data_dir=tmp_path),
    )


def test_recognize_many_returns_one_result_per_quad(seeded, tmp_path):
    service = _service(seeded, tmp_path, _FakeIndex())
    quads = [np.array([[0, 0], [600, 0], [600, 825], [0, 825]], dtype="float32")]
    results = service.recognize_many(_crop(1200, 825), quads)
    assert len(results) == 1
    quad, result, centering = results[0]
    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.rectified_path is not None  # persisted per winning crop


def test_recognize_many_preserves_not_found_per_crop(seeded, tmp_path):
    service = _service(seeded, tmp_path, _FakeIndex(score=-1.0))
    quads = [np.array([[0, 0], [600, 0], [600, 825], [0, 825]], dtype="float32")]
    results = service.recognize_many(_crop(1200, 825), quads)
    assert len(results) == 1
    _, result, _ = results[0]
    assert result.status == "not_found"
    assert result.card_id is None
    assert result.rectified_path is None


def test_recognize_many_empty_quads_returns_empty(seeded, tmp_path):
    service = _service(seeded, tmp_path, _FakeIndex())
    assert service.recognize_many(_crop(1200, 825), []) == []


def test_recognize_many_multiple_quads(seeded, tmp_path):
    service = _service(seeded, tmp_path, _FakeIndex())
    quads = [
        np.array([[0, 0], [400, 0], [400, 825], [0, 825]], dtype="float32"),
        np.array([[400, 0], [800, 0], [800, 825], [400, 825]], dtype="float32"),
    ]
    results = service.recognize_many(_crop(800, 825), quads)
    assert len(results) == 2
    assert all(r.status == "confident" for _, r, _ in results)
    assert all(r.rectified_path is not None for _, r, _ in results)