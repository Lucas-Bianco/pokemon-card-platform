import numpy as np
import pytest
from PIL import Image

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


def _photo():
    return Image.new("RGB", (600, 825), (180, 40, 40))


def test_confident_match_returns_card(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("base1-4", 0.9), Candidate("base4-4", 0.6)]),
        reader=FakeReader(),
    )

    result = service.recognize(_photo(), rectify=False)

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

    result = service.recognize(_photo(), rectify=False)

    assert result.card_id == "me2pt5-114"
    assert result.status == "confident"


def test_ambiguous_result_returns_candidates(seeded):
    service = RecognitionService(
        session=seeded,
        encoder=FakeEncoder(),
        index=FakeIndex([Candidate("me2pt5-252", 0.781), Candidate("me2pt5-114", 0.775)]),
        reader=FakeReader(),
    )

    result = service.recognize(_photo(), rectify=False)

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

    result = service.recognize(_photo(), rectify=False)

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

    result = service.recognize(blank, rectify=True)

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

    result = service.recognize(_photo(), rectify=False)

    assert result.status == "not_found"
    assert result.candidates == ()
