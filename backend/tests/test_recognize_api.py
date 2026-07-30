"""/recognize contract tests.

Every test overrides get_recognition_service with a stub, so no CLIP weights are ever
loaded and no FAISS index has to exist on disk — get_recognition_stack() must stay
untouched for the whole module.
"""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cardplatform.api import app, get_recognition_service, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.recognition.types import Candidate, OcrReading, RecognitionResult

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


class StubService:
    """Stands in for RecognitionService; records the rectify flag it was called with."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def recognize(self, image, rectify=True):
        self.calls.append(rectify)
        return self.result


def result(
    card_id="base1-4",
    confidence=0.94,
    status="confident",
    candidates=(Candidate(card_id="base1-4", visual_score=0.91),),
    ocr=OcrReading(collector_number="4", printed_total="102"),
    visual_margin=0.22,
):
    return RecognitionResult(
        card_id=card_id,
        confidence=confidence,
        status=status,
        candidates=tuple(candidates),
        ocr=ocr,
        visual_margin=visual_margin,
    )


def photo_bytes(color=(220, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 84), color).save(buffer, format="PNG")
    return buffer.getvalue()


def upload(client, params=None, content=None):
    return client.post(
        "/recognize",
        params=params or {},
        files={"file": ("card.png", content if content is not None else photo_bytes(),
                        "image/png")},
    )


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
    db.add(Card(id="base1-58", set_id="base1", name="Pikachu", number="58"))
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
def make_client(seeded):
    stubs = []

    def _make(recognition_result) -> TestClient:
        stub = StubService(recognition_result)
        stubs.append(stub)
        app.dependency_overrides[get_session] = lambda: seeded
        app.dependency_overrides[get_recognition_service] = lambda: stub
        client = TestClient(app)
        client.stub = stub
        return client

    yield _make
    app.dependency_overrides.clear()


def test_confident_result_returns_the_card_with_its_priced_source_timestamp(make_client):
    """A price is worthless to the UI without a stamp: cardmarket has been measured
    ~4 weeks behind tcgplayer on the same card on the same day."""
    client = make_client(result())

    response = upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confident"
    assert body["confidence"] == 0.94
    assert body["visual_margin"] == 0.22
    assert body["card"]["id"] == "base1-4"
    assert body["card"]["name"] == "Charizard"
    assert body["card"]["set_name"] == "Base"
    assert body["price"]["source"] == "tcgplayer"
    assert body["price"]["variant"] == "normal"
    assert body["price"]["market"] == 800.43
    assert body["price"]["source_updated_at"] == "2026/07/29"


def test_collector_number_read_reports_what_ocr_saw(make_client):
    """Surfacing the read digits lets the user see why the pipeline chose this card."""
    client = make_client(result(ocr=OcrReading(collector_number="4", printed_total="102")))

    body = upload(client).json()

    assert body["collector_number_read"] == "4"


def test_collector_number_read_is_null_when_ocr_read_nothing(make_client):
    client = make_client(result(ocr=OcrReading()))

    assert upload(client).json()["collector_number_read"] is None


def test_ambiguous_result_returns_no_card_but_named_candidates(make_client):
    """The user has to pick, so each candidate needs a name and picture — a bare id
    is unusable in the UI."""
    client = make_client(
        result(
            card_id=None,
            status="ambiguous",
            confidence=0.41,
            candidates=(
                Candidate(card_id="base1-4", visual_score=0.63),
                Candidate(card_id="base1-58", visual_score=0.61),
            ),
        )
    )

    body = upload(client).json()

    assert body["status"] == "ambiguous"
    assert body["card"] is None
    assert body["price"] is None
    assert [c["card_id"] for c in body["candidates"]] == ["base1-4", "base1-58"]
    assert [c["name"] for c in body["candidates"]] == ["Charizard", "Pikachu"]
    assert body["candidates"][0]["set_name"] == "Base"
    assert body["candidates"][0]["number"] == "4"
    assert body["candidates"][0]["image_small"] == "https://images.example/base1-4/small.png"
    assert body["candidates"][0]["visual_score"] == 0.63


def test_not_found_result_returns_no_card_and_no_candidates(make_client):
    client = make_client(
        result(card_id=None, status="not_found", confidence=0.0, candidates=(),
               ocr=OcrReading(), visual_margin=0.0)
    )

    body = upload(client).json()

    assert body["status"] == "not_found"
    assert body["card"] is None
    assert body["price"] is None
    assert body["candidates"] == []


def test_an_upload_that_is_not_an_image_is_a_400_not_a_500(make_client):
    """A phone can upload anything. A decode failure is the client's problem and must
    read as one rather than as a server crash."""
    client = make_client(result())

    response = upload(client, content=b"this is not a picture")

    assert response.status_code == 400
    assert "image" in response.json()["detail"].lower()
    assert client.stub.calls == []


def test_rectify_query_param_reaches_the_service(make_client):
    """Phase 1b's PWA rectifies client-side in WebAssembly; rectifying again would
    warp an already-flat card."""
    client = make_client(result())

    assert upload(client, params={"rectify": "false"}).status_code == 200
    assert client.stub.calls == [False]

    assert upload(client).status_code == 200
    assert client.stub.calls == [False, True]


def test_an_unpriced_card_still_returns_the_card_with_a_null_price(make_client):
    """Most of the 20k-card catalog has never been priced; that is a normal scan
    result, not a failure to recognise."""
    client = make_client(
        result(card_id="base1-58", candidates=(Candidate(card_id="base1-58", visual_score=0.9),))
    )

    body = upload(client).json()

    assert body["card"]["id"] == "base1-58"
    assert body["price"] is None


def test_a_candidate_missing_from_the_catalog_is_skipped_not_fatal(make_client):
    """A stale index can name an id the catalog dropped. Skip it rather than 500."""
    client = make_client(
        result(
            card_id=None,
            status="ambiguous",
            candidates=(
                Candidate(card_id="ghost-999", visual_score=0.7),
                Candidate(card_id="base1-4", visual_score=0.69),
            ),
        )
    )

    response = upload(client)

    assert response.status_code == 200
    assert [c["card_id"] for c in response.json()["candidates"]] == ["base1-4"]
