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
    """Stands in for RecognitionService; records the arguments it was called with.

    `corners` starts as the sentinel "unset" so a test can tell "the endpoint passed
    None" apart from "the endpoint never called us at all".
    """

    def __init__(self, result, centering=None):
        self.result = result
        self.centering = centering
        self.calls = []
        self.corners = "unset"

    def recognize(self, image, rectify=True, corners=None):
        self.calls.append(rectify)
        self.corners = corners
        # The service returns (result, centering); centering is None whenever the
        # border could not be measured, which is the common case on real cards.
        return self.result, self.centering


def result(
    card_id="base1-4",
    confidence=0.94,
    status="confident",
    candidates=(Candidate(card_id="base1-4", visual_score=0.91),),
    ocr=OcrReading(collector_number="4", printed_total="102"),
    visual_margin=0.22,
    rectified_path=None,
):
    return RecognitionResult(
        card_id=card_id,
        confidence=confidence,
        status=status,
        candidates=tuple(candidates),
        ocr=ocr,
        visual_margin=visual_margin,
        rectified_path=rectified_path,
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

    def _make(recognition_result, centering=None) -> TestClient:
        stub = StubService(recognition_result, centering)
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


def test_rectified_path_is_returned_in_the_response(make_client):
    """The persisted crop's path is surfaced so the frontend can pass it back to
    /scans and record it on the scan_logs row for grading."""
    client = make_client(result(rectified_path="rectified/abc.png"))

    body = upload(client).json()

    assert body["rectified_path"] == "rectified/abc.png"


def test_rectified_path_is_null_when_no_crop_was_produced(make_client):
    client = make_client(not_found_result())

    assert upload(client).json()["rectified_path"] is None


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


def not_found_result():
    return result(card_id=None, status="not_found", confidence=0.0, candidates=(),
                  ocr=OcrReading(), visual_margin=0.0)


def test_manual_corners_are_passed_to_the_service(make_client):
    """Hand-placed corners are the fallback for the 36 real scans that come back
    ambiguous, so they must survive the trip to the service unrounded and in order."""
    client = make_client(result())

    response = upload(client, params={"corners": "10,20,110,20,110,160,10,160"})

    assert response.status_code == 200
    assert client.stub.corners == [(10.0, 20.0), (110.0, 20.0), (110.0, 160.0), (10.0, 160.0)]


def test_corners_default_to_none(make_client):
    """Omitting corners must not change existing behaviour."""
    client = make_client(not_found_result())

    upload(client)

    assert client.stub.corners is None


def test_corners_with_wrong_count_are_rejected(make_client):
    client = make_client(not_found_result())

    response = upload(client, params={"corners": "1,2,3"})

    assert response.status_code == 422
    assert client.stub.corners == "unset"


def test_non_numeric_corners_are_rejected(make_client):
    client = make_client(not_found_result())

    response = upload(client, params={"corners": "a,b,c,d,e,f,g,h"})

    assert response.status_code == 422
    assert client.stub.corners == "unset"


def centering_result(worst_axis=54.0, uncertainty=1.0, psa_cap=10, certain=True):
    from cardplatform.grading.centering import CenteringResult

    return CenteringResult(
        left_right=(worst_axis, 100.0 - worst_axis),
        top_bottom=(50.0, 50.0),
        worst_axis=worst_axis,
        uncertainty=uncertainty,
        border_pixels=(23, 17, 20, 20),
        psa_cap=psa_cap,
        psa_cap_certain=certain,
    )


def test_centering_is_returned_when_measurable(make_client):
    client = make_client(result(), centering=centering_result())

    body = upload(client).json()

    assert body["centering"]["worst_axis"] == 54.0
    assert body["centering"]["psa_cap"] == 10
    assert body["centering"]["left_right"] == [54.0, 46.0]


def test_centering_is_null_when_the_border_could_not_be_measured(make_client):
    """The common case on real cards — modern textured frames cannot be measured."""
    client = make_client(result(), centering=None)

    assert upload(client).json()["centering"] is None


def test_cap_range_is_null_when_the_cap_is_certain(make_client):
    client = make_client(result(), centering=centering_result(certain=True))

    assert upload(client).json()["centering"]["psa_cap_range"] is None


def test_cap_range_names_both_grades_when_the_interval_straddles_a_boundary(make_client):
    """54.5 +/- 2.5 spans 52.0-57.0, crossing the 55 line between PSA 10 and 9."""
    client = make_client(
        result(),
        centering=centering_result(worst_axis=54.5, uncertainty=2.5, psa_cap=10, certain=False),
    )

    assert upload(client).json()["centering"]["psa_cap_range"] == [9, 10]


def test_cap_range_is_ordered_low_to_high():
    """Better centering yields the HIGHER grade, so the low end of the interval maps to
    the top of the range. Backwards, this would understate every uncertain card."""
    from cardplatform.api import _psa_cap_range

    assert _psa_cap_range(
        centering_result(worst_axis=59.5, uncertainty=1.5, psa_cap=9, certain=False)
    ) == (8, 9)


def test_cap_range_is_null_when_one_end_leaves_every_band():
    """Past the last published band (90/10) there is no bound to state, and inventing
    one would be worse than saying nothing. 88 +/- 5 spans 83-93, and 93 has no cap."""
    from cardplatform.api import _psa_cap_range

    assert _psa_cap_range(
        centering_result(worst_axis=88.0, uncertainty=5.0, psa_cap=3, certain=False)
    ) is None


def test_cap_range_spans_the_lower_bands_too():
    """The table runs past 6 to grades 5 and 3, so the range logic must work there."""
    from cardplatform.api import _psa_cap_range

    assert _psa_cap_range(
        centering_result(worst_axis=79.0, uncertainty=4.0, psa_cap=6, certain=False)
    ) == (5, 6)
