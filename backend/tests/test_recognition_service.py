import numpy as np
import pytest
from PIL import Image

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet
from cardplatform.recognition.service import RecognitionService
from cardplatform.recognition.types import Candidate, OcrReading


class FakeEncoder:
    dimension = 4

    def __init__(self):
        self.embedded = []

    def embed(self, image):
        self.embedded.append(image)
        return np.array([1, 0, 0, 0], dtype=np.float32)


class FakeIndex:
    def __init__(self, candidates):
        self._candidates = candidates
        self.top_k_requested = None

    def search(self, vector, top_k):
        self.top_k_requested = top_k
        return list(self._candidates)[:top_k]


class FakeReader:
    def __init__(self, reading=None):
        self._reading = reading or OcrReading()
        self.read_images = []

    def read(self, image):
        self.read_images.append(image)
        return self._reading


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base4-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="me2pt5-114", set_id="base1", name="Stunfisk ex", number="114"))
    db.add(Card(id="me2pt5-252", set_id="base1", name="Stunfisk ex", number="252"))
    db.commit()
    return db


@pytest.fixture(autouse=True)
def _tmp_default_settings(tmp_path, monkeypatch):
    """Point the module-level default Settings at tmp_path so recognition's
    rectified-image persistence never writes into the real data/ directory.

    Tests that pass an explicit `settings=` (the _service_with_tmp_dir helper) still
    win because `settings or default_settings` prefers the argument.
    """
    from cardplatform.recognition import service as service_module

    monkeypatch.setattr(service_module, "default_settings", Settings(data_dir=tmp_path))


def _photo():
    return Image.new("RGB", (600, 825), (180, 40, 40))


def test_confident_match_returns_card(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
    )

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.status == "confident"
    assert result.card_id == "base1-4"


def test_ocr_disambiguates_same_name_reprints(seeded):
    """The real measured failure mode, end to end through the service."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775)]),
        reader=FakeReader(OcrReading(collector_number="114", printed_total="252")),
    )

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_ambiguous_result_returns_candidates(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775)]),
        reader=FakeReader(),
    )

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.status == "ambiguous"
    assert [c.card_id for c in result.candidates] == ["me2pt5-252", "me2pt5-114"]


def test_candidates_unknown_to_the_catalog_are_dropped(seeded):
    """An index entry for a card since removed from the catalog must not crash."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("ghost-1", 0.95), Candidate("base1-4", 0.60)]),
        reader=FakeReader(),
    )

    result, _centering = service.recognize(_photo(), rectify=False)

    assert all(c.card_id != "ghost-1" for c in result.candidates)


def test_rectification_failure_is_reported(seeded):
    """A photo with no detectable card returns not_found rather than guessing."""
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=FakeReader(),
    )
    blank = Image.new("RGB", (900, 700), (18, 18, 18))

    result, _centering = service.recognize(blank, rectify=True)

    assert result.status == "not_found"
    assert result.card_id is None


def test_rectification_failure_does_not_call_encoder_or_ocr(seeded):
    """Cheap guard: no point embedding or OCR-ing a frame with no card in it."""
    encoder = FakeEncoder()
    reader = FakeReader()
    service = RecognitionService(
        session=seeded,
        encoder=encoder,
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=reader,
    )

    service.recognize(Image.new("RGB", (900, 700), (18, 18, 18)), rectify=True)

    assert encoder.embedded == []
    assert reader.read_images == []


def test_encoder_and_ocr_see_the_same_image(seeded):
    """Both engines must analyse the identical rectified crop, or their signals
    are not describing the same thing."""
    encoder = FakeEncoder()
    reader = FakeReader()
    service = RecognitionService(
        session=seeded,
        encoder=encoder,
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=reader,
    )
    photo = _photo()

    service.recognize(photo, rectify=False)

    assert encoder.embedded[0] is reader.read_images[0]


def test_top_k_comes_from_settings(seeded):
    index = FakeIndex([Candidate("base1-4", 0.9)])
    service = RecognitionService(
        session=seeded, encoder=FakeEncoder(), index=index, reader=FakeReader()
    )

    service.recognize(_photo(), rectify=False)

    assert index.top_k_requested == 5


def test_empty_candidate_list_is_not_found(seeded):
    service = RecognitionService(
        session=seeded, encoder=FakeEncoder(), index=FakeIndex([]), reader=FakeReader()
    )

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.status == "not_found"
    assert result.candidates == ()


class ScriptedIndex:
    """Returns a different result per call, so proposal selection is observable."""

    def __init__(self, per_call):
        self.per_call = list(per_call)
        self.calls = 0

    def search(self, vector, top_k):
        result = self.per_call[min(self.calls, len(self.per_call) - 1)]
        self.calls += 1
        return list(result)[:top_k]


class CountingReader:
    def __init__(self):
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return OcrReading()


def test_best_scoring_proposal_wins(seeded, monkeypatch):
    """Two detectors propose different crops; the better-matching one wins."""
    from cardplatform.recognition import service as service_module

    quad_a = np.array([[0, 0], [100, 0], [100, 140], [0, 140]], dtype="float32")
    quad_b = np.array([[10, 10], [110, 10], [110, 150], [10, 150]], dtype="float32")
    monkeypatch.setattr(
        service_module, "detect_candidates", lambda image: [("a", quad_a), ("b", quad_b)]
    )

    index = ScriptedIndex(
        [
            (Candidate("base1-4", 0.60), Candidate("base4-4", 0.59)),
            (Candidate("me2pt5-114", 0.93), Candidate("me2pt5-252", 0.70)),
        ]
    )
    service = RecognitionService(
        session=seeded, encoder=FakeEncoder(), index=index, reader=FakeReader()
    )

    result, _centering = service.recognize(Image.new("RGB", (300, 400), (200, 40, 40)), rectify=True)

    assert result.card_id == "me2pt5-114"


def test_ocr_runs_once_not_per_proposal(seeded, monkeypatch):
    """OCR costs ~1s. Running it per proposal would triple scan time for nothing."""
    from cardplatform.recognition import service as service_module

    quad = np.array([[0, 0], [100, 0], [100, 140], [0, 140]], dtype="float32")
    monkeypatch.setattr(
        service_module,
        "detect_candidates",
        lambda image: [("a", quad), ("b", quad), ("c", quad)],
    )
    reader = CountingReader()
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=reader,
    )

    service.recognize(Image.new("RGB", (300, 400), (200, 40, 40)), rectify=True)

    assert reader.calls == 1


def test_no_proposals_is_not_found(seeded, monkeypatch):
    from cardplatform.recognition import service as service_module

    monkeypatch.setattr(service_module, "detect_candidates", lambda image: [])
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9)]),
        reader=FakeReader(),
    )

    result, _centering = service.recognize(Image.new("RGB", (300, 400), (18, 18, 18)), rectify=True)

    assert result.status == "not_found"


def test_proposal_with_no_search_hits_still_yields_a_real_crop(seeded, monkeypatch):
    """A card was detected but the index matched nothing — OCR must still receive the
    rectified crop. Scoring proposals from a -1.0 floor let a no-hit proposal fail to
    beat it, leaving the winning crop unset and handing the reader None."""
    from cardplatform.recognition import service as service_module

    quad = np.array([[0, 0], [100, 0], [100, 140], [0, 140]], dtype="float32")
    monkeypatch.setattr(service_module, "detect_candidates", lambda image: [("a", quad)])
    reader = FakeReader()
    service = RecognitionService(
        session=seeded, encoder=FakeEncoder(), index=FakeIndex([]), reader=reader
    )

    result, _centering = service.recognize(Image.new("RGB", (300, 400), (200, 40, 40)), rectify=True)

    assert result.status == "not_found"
    assert isinstance(reader.read_images[0], Image.Image)


def test_manual_corners_bypass_detection(seeded, monkeypatch):
    """The fallback path: the user dragged the corners, so trust them."""
    from cardplatform.recognition import service as service_module

    def _should_not_run(image):
        raise AssertionError("detection must be skipped when corners are supplied")

    monkeypatch.setattr(service_module, "detect_candidates", _should_not_run)
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
    )

    result, _centering = service.recognize(
        Image.new("RGB", (300, 400), (200, 40, 40)),
        rectify=True,
        corners=[(0, 0), (100, 0), (100, 140), (0, 140)],
    )

    assert result.status == "confident"


def _service_with_tmp_dir(seeded, tmp_path, **index_kwargs):
    """A RecognitionService whose rectified_image_dir lives under tmp_path, so tests
    can assert the PNG landed there without touching the real data directory."""
    return RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
        settings=Settings(data_dir=tmp_path),
        **index_kwargs,
    )


def test_rectified_crop_is_persisted(seeded, tmp_path):
    """The crop passed to centering is written to the rectified dir and its relative
    path is surfaced on the result for the API to record."""
    service = _service_with_tmp_dir(seeded, tmp_path)

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.status == "confident"
    assert result.rectified_path is not None
    assert result.rectified_path.startswith("rectified/")
    saved = tmp_path / result.rectified_path
    assert saved.exists()
    assert Image.open(saved).size == (600, 825)


def test_not_found_leaves_rectified_path_none(seeded, tmp_path, monkeypatch):
    """No proposals -> no crop -> nothing persisted. The dir must not even be created."""
    from cardplatform.recognition import service as service_module

    monkeypatch.setattr(service_module, "detect_candidates", lambda image: [])
    service = _service_with_tmp_dir(seeded, tmp_path)

    result, _centering = service.recognize(
        Image.new("RGB", (300, 400), (18, 18, 18)), rectify=True
    )

    assert result.status == "not_found"
    assert result.rectified_path is None
    assert not (tmp_path / "rectified").exists()


def test_rectified_persistence_failure_is_fail_soft(seeded, tmp_path):
    """If the rectified dir cannot be written, recognition still succeeds and the
    path is None — persistence is additive, never load-bearing."""
    # Place a FILE where the rectified directory would be, so mkdir/save raises.
    (tmp_path / "rectified").write_bytes(b"")
    service = _service_with_tmp_dir(seeded, tmp_path)

    result, _centering = service.recognize(_photo(), rectify=False)

    assert result.status == "confident"
    assert result.rectified_path is None
