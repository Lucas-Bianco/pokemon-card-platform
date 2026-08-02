"""T5: grading-upside HTTP endpoint — the price spread, with honest empty states.

This is NOT a grade prediction. The endpoint returns the spread between today's
raw market price and PSA-9 / PSA-10 market prices (minus the bulk grading fee),
and every test here pins the honest-data contract at the boundary: missing
snapshots surface as null (never a fabricated $0), `upside_to_10` is null unless
BOTH raw and psa10 are present, and `graded_prices_unavailable` is true only
when both graded tiers are absent. Unknown card is 404, not an empty 200.

Snapshots are inserted directly into the tables (no real network): the read-only
PriceService / GradedPriceService construct without providers, exactly as the
endpoint builds them, so latest_price / latest_graded — the only sanctioned
resolvers — are exercised for real.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, GradedPriceSnapshot, PriceSnapshot

# The default grading fee from config.grading_fee (T1, PSA bulk ~$25/card).
DEFAULT_FEE = 25.0


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def _raw(db, variant="holofoil", market=120.0, source="tcgplayer",
         source_updated_at="2026/07/29"):
    db.add(PriceSnapshot(
        card_id="base1-4",
        source=source,
        variant=variant,
        market=market,
        source_updated_at=source_updated_at,
    ))
    db.commit()


def _graded(db, grade, variant="holofoil", market=350.0, grader="PSA",
            source="pkmnprices", source_updated_at="2026/07/28"):
    db.add(GradedPriceSnapshot(
        card_id="base1-4",
        grader=grader,
        grade=grade,
        variant=variant,
        market=market,
        source=source,
        source_updated_at=source_updated_at,
    ))
    db.commit()


def _upside(client, variant="holofoil"):
    return client.get("/cards/base1-4/grading-upside", params={"variant": variant})


# --- Full spread: all three tiers present ------------------------------------

def test_full_spade_computes_upside_to_10(seeded, client):
    """raw + psa9 + psa10 all present -> upside_to_10 == psa10.market - raw.market - fee."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=9.0, market=350.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _upside(client).json()

    assert body["raw_price"] == {"market": 120.0, "source": "tcgplayer",
                                 "source_updated_at": "2026/07/29"}
    assert body["psa9"] == {"market": 350.0, "source": "pkmnprices",
                           "source_updated_at": "2026/07/28"}
    assert body["psa10"] == {"market": 1200.0, "source": "pkmnprices",
                            "source_updated_at": "2026/07/28"}
    assert body["grading_fee"] == DEFAULT_FEE
    assert body["upside_to_10"] == 1200.0 - 120.0 - DEFAULT_FEE
    assert body["upside_to_10"] == 1055.0
    assert body["graded_prices_unavailable"] is False
    assert body["card_id"] == "base1-4"
    assert body["variant"] == "holofoil"


# --- Honest empty states ----------------------------------------------------

def test_no_graded_prices_surfaces_nulls_and_unavailable_flag(seeded, client):
    """psa9/psa10 both None, raw present -> both null, upside null, unavailable true."""
    _raw(seeded, market=120.0)

    body = _upside(client).json()

    assert body["raw_price"]["market"] == 120.0
    assert body["psa9"] is None
    assert body["psa10"] is None
    assert body["upside_to_10"] is None
    assert body["graded_prices_unavailable"] is True


def test_no_raw_price_surfaces_null_raw_and_null_upside(seeded, client):
    """raw None, graded present -> raw_price null, upside null (can't compute),
    graded_prices_unavailable FALSE (graded ARE available)."""
    _graded(seeded, grade=9.0, market=350.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _upside(client).json()

    assert body["raw_price"] is None
    assert body["psa9"]["market"] == 350.0
    assert body["psa10"]["market"] == 1200.0
    assert body["upside_to_10"] is None  # can't compute without raw
    assert body["graded_prices_unavailable"] is False  # graded ARE available


def test_neither_raw_nor_graded_everything_null(seeded, client):
    """No snapshots at all -> everything null except grading_fee, unavailable true."""
    body = _upside(client).json()

    assert body["raw_price"] is None
    assert body["psa9"] is None
    assert body["psa10"] is None
    assert body["grading_fee"] == DEFAULT_FEE
    assert body["upside_to_10"] is None
    assert body["graded_prices_unavailable"] is True


def test_only_psa9_present_psa10_null(seeded, client):
    """psa9 present, psa10 null, raw present -> upside null (needs psa10 specifically),
    graded_prices_unavailable FALSE (a lone psa9 proves graded prices exist)."""
    _raw(seeded, market=120.0)
    _graded(seeded, grade=9.0, market=350.0)

    body = _upside(client).json()

    assert body["raw_price"]["market"] == 120.0
    assert body["psa9"]["market"] == 350.0
    assert body["psa10"] is None
    assert body["upside_to_10"] is None  # needs psa10 specifically
    assert body["graded_prices_unavailable"] is False


# --- 404 / fee --------------------------------------------------------------

def test_unknown_card_returns_404(client):
    """Unknown card is 404, not an empty 200 (mirrors /cards/{id}/price)."""
    response = client.get("/cards/nope-1/grading-upside", params={"variant": "holofoil"})
    assert response.status_code == 404
    assert "unknown card" in response.json()["detail"]


def test_grading_fee_always_equals_settings_default(seeded, client):
    """With no snapshots the fee still surfaces — it never depends on pricing."""
    body = _upside(client).json()
    assert body["grading_fee"] == DEFAULT_FEE


def test_grading_fee_reflects_custom_setting(seeded, db, tmp_path, monkeypatch):
    """A custom grading_fee in Settings flows through to the response."""
    _raw(seeded, market=100.0)
    _graded(seeded, grade=10.0, market=500.0)

    # Point the module-level settings at a custom instance, then restore it.
    from cardplatform.grading import upside as upside_module
    custom = Settings(data_dir=tmp_path)
    # data_dir does not affect grading_fee; override it directly.
    monkeypatch.setattr(custom, "grading_fee", 50.0)
    monkeypatch.setattr(upside_module, "settings", custom)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    client = TestClient(app)

    body = client.get("/cards/base1-4/grading-upside",
                      params={"variant": "holofoil"}).json()

    assert body["grading_fee"] == 50.0
    assert body["upside_to_10"] == 500.0 - 100.0 - 50.0  # 350.0


# --- Variant scoping --------------------------------------------------------

def test_variant_is_required_query_param(seeded, client):
    """variant is required (the raw price is variant-specific); omitting it 422s."""
    response = client.get("/cards/base1-4/grading-upside")
    assert response.status_code == 422


def test_variant_scopes_raw_and_graded_lookups(seeded, client):
    """Asking for holofoil must not pull in reverseHolofoil snapshots — a spread
    mixing variants is not a spread of one card's price."""
    _raw(seeded, variant="holofoil", market=120.0)
    _raw(seeded, variant="reverseHolofoil", market=20.0)
    _graded(seeded, grade=10.0, variant="holofoil", market=1200.0)
    _graded(seeded, grade=10.0, variant="reverseHolofoil", market=40.0)

    body = _upside(client, variant="holofoil").json()

    assert body["raw_price"]["market"] == 120.0
    assert body["psa10"]["market"] == 1200.0
    assert body["upside_to_10"] == 1200.0 - 120.0 - DEFAULT_FEE