import pytest

from cardplatform.config import Settings
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult


def test_settings_expose_recognition_paths(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.reference_image_dir == tmp_path / "reference_images"
    assert s.index_path == tmp_path / "card_index.faiss"
    assert s.index_ids_path == tmp_path / "card_index_ids.json"


def test_settings_expose_encoder_defaults(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.encoder_model == "ViT-B-32"
    assert s.encoder_pretrained == "laion2b_s34b_b79k"
    assert s.rectified_size == (600, 825)


def test_candidate_is_frozen():
    c = Candidate(card_id="base1-4", visual_score=0.91)
    with pytest.raises(Exception):
        c.card_id = "other"


def test_ocr_reading_defaults_are_empty():
    r = OcrReading()
    assert r.collector_number is None
    assert r.printed_total is None
    assert r.raw_regions == ()


def test_recognition_result_reports_status():
    result = RecognitionResult(
        card_id="base1-4",
        confidence=0.95,
        status="confident",
        candidates=(Candidate("base1-4", 0.91),),
        ocr=OcrReading(collector_number="4", printed_total="102"),
        visual_margin=0.14,
    )
    assert result.status == "confident"
    assert result.card_id == "base1-4"
    assert result.candidates[0].card_id == "base1-4"
