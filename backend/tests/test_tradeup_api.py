"""T5: trade-up HTTP endpoint — the honest exit-strategy simulator (row 19).

Pins the wire contract at the boundary: the route is read-only, unknown card is
404, `variant` is required, both legs surface source/staleness, missing legs are
null (never $0), the recommendation is descriptive, and the seeded sold-comps
provider is exercised for real via the route's EbayListingsProvider(catalog=...)
construction — monkeypatched to a stub so no network is touched.

Mirrors test_grading_upside_api.py: direct snapshot inserts + a dependency
override for get_session. The EbayListingsProvider is patched on the api module
to a stub returning fixed SoldComps so the raw-leg median is deterministic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, GradedPriceSnapshot, PriceSnapshot
from cardplatform.prices.listings_provider import SoldComp

DEFAULT_SELLING_FEE = 0.13
DEFAULT_GRADING_FEE = 25.0


class StubEbayProvider:
    """Stands in for EbayListingsProvider at the route's construction site. The
    route builds `EbayListingsProvider(catalog=_catalog_lookup(session))` —
    patching the symbol on the api module swaps that call to this stub, which
    ignores the catalog kwarg and returns fixed comps per (card_id, variant)."""

    def __init__(self, comps_by_key, *args, **kwargs):
        self.comps_by_key = comps_by_key
        self.calls: list[tuple[str, str, int]] = []

    def fetch_sold_listings(self, card_id, variant, limit=3):
        self.calls.append((card_id, variant, limit))
        return list(self.comps_by_key.get((card_id, variant), []))


def _comp(price, card_id="base1-4", variant="holofoil"):
    return SoldComp(card_id=card_id, variant=variant, listing_id=f"l{price}",
                    price=price, title="Charizard", currency="USD")


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


@pytest.fixture
def client(seeded, monkeypatch):
    """A client whose route uses a stub EbayListingsProvider returning fixed
    comps for (base1-4, holofoil)."""
    comps = {("base1-4", "holofoil"): [_comp(118.0), _comp(121.0), _comp(119.0)]}
    stub_cls = StubEbayProvider
    # Patch the name the route references (imported into api.py's namespace).
    import cardplatform.api as api_module
    monkeypatch.setattr(api_module, "EbayListingsProvider",
                        lambda *a, **kw: stub_cls(comps, *a, **kw))
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    return TestClient(app)


def _raw(db, variant="holofoil", market=120.0, source="tcgplayer",
         source_updated_at="2026/07/29"):
    db.add(PriceSnapshot(
        card_id="base1-4", source=source, variant=variant, market=market,
        source_updated_at=source_updated_at,
    ))
    db.commit()


def _graded(db, grade, variant="holofoil", market=1200.0, grader="PSA",
            source="pkmnprices", source_updated_at="2026/07/28"):
    db.add(GradedPriceSnapshot(
        card_id="base1-4", grader=grader, grade=grade, variant=variant,
        market=market, source=source, source_updated_at=source_updated_at,
    ))
    db.commit()


def _tradeup(client, variant="holofoil", **kw):
    params = {"variant": variant}
    params.update(kw)
    return client.get("/cards/base1-4/trade-up", params=params)


# --- Full assessment: both legs priced --------------------------------------

def test_full_assessment_shape(seeded, client):
    _raw(seeded, market=300.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _tradeup(client).json()

    assert body["card_id"] == "base1-4"
    assert body["variant"] == "holofoil"
    assert body["grader"] == "PSA"
    assert body["target_grade"] == 10.0
    # raw leg: median of [118,121,119] == 119, net of 13%
    assert body["raw_leg"]["gross"] == 119.0
    assert body["raw_leg"]["fee"] == pytest.approx(119.0 * DEFAULT_SELLING_FEE)
    assert body["raw_leg"]["net"] == pytest.approx(119.0 * (1 - DEFAULT_SELLING_FEE))
    assert body["raw_leg"]["source"] == "ebay_sold_median"
    assert body["raw_leg"]["evidence_count"] == 3
    # grade leg: 1200 net of grading_fee + 13%
    assert body["grade_leg"]["gross"] == 1200.0
    assert body["grade_leg"]["source"] == "pkmnprices"
    assert body["grade_leg"]["source_updated_at"] == "2026/07/28"
    # market reference (ask) for context — NOT the sell price
    assert body["market_reference"] == 300.0
    assert body["market_reference_source"] == "tcgplayer"
    # grade nets more -> descriptive recommendation
    assert body["recommendation"] == "grade"
    assert body["centering_blocks_grading"] is False
    assert isinstance(body["caveats"], list) and body["caveats"]


# --- Honest empty states ----------------------------------------------------

def test_no_comps_yields_null_raw_leg(seeded, client, monkeypatch):
    """Patch the stub to return no comps -> raw leg null, never $0."""
    import cardplatform.api as api_module
    monkeypatch.setattr(api_module, "EbayListingsProvider",
                        lambda *a, **kw: StubEbayProvider({}, *a, **kw))
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _tradeup(client).json()

    assert body["raw_leg"]["gross"] is None
    assert body["raw_leg"]["fee"] is None
    assert body["raw_leg"]["net"] is None
    assert body["raw_leg"]["evidence_count"] == 0
    assert body["raw_leg"]["note"]  # the honest reason


def test_no_graded_price_yields_null_grade_leg(seeded, client, monkeypatch):
    _raw(seeded, market=120.0)
    # no graded snapshot
    body = _tradeup(client).json()

    assert body["grade_leg"]["gross"] is None
    assert body["grade_leg"]["net"] is None
    assert body["grade_leg"]["note"]
    # only raw leg estimable -> sell_raw
    assert body["recommendation"] == "sell_raw"


def test_neither_leg_estimable_yields_null_recommendation(seeded, client, monkeypatch):
    """No comps AND no graded price -> recommendation None (not a guess)."""
    import cardplatform.api as api_module
    monkeypatch.setattr(api_module, "EbayListingsProvider",
                        lambda *a, **kw: StubEbayProvider({}, *a, **kw))
    _raw(seeded, market=120.0)  # ask only

    body = _tradeup(client).json()

    assert body["raw_leg"]["net"] is None
    assert body["grade_leg"]["net"] is None
    assert body["recommendation"] is None


# --- Centering cap via query param ------------------------------------------

def test_centering_cap_query_param_blocks_grading(seeded, client):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _tradeup(client, grade=10, centering_cap=8).json()

    assert body["centering_cap"] == 8
    assert body["centering_blocks_grading"] is True
    # figure still reported
    assert body["grade_leg"]["gross"] == 1200.0
    # centering rules out grading -> sell_raw is the only real option
    assert body["recommendation"] == "sell_raw"


def test_target_grade_query_param_selects_tier(seeded, client):
    _raw(seeded, market=120.0)
    _graded(seeded, grade=9.0, market=350.0)
    _graded(seeded, grade=10.0, market=1200.0)

    body = _tradeup(client, grade=9).json()

    assert body["target_grade"] == 9.0
    assert body["grade_leg"]["gross"] == 350.0  # PSA-9, not PSA-10


# --- 404 / required params --------------------------------------------------

def test_unknown_card_returns_404(client):
    r = client.get("/cards/nope-1/trade-up", params={"variant": "holofoil"})
    assert r.status_code == 404
    assert "unknown card" in r.json()["detail"]


def test_variant_is_required(client):
    r = client.get("/cards/base1-4/trade-up")
    assert r.status_code == 422


# --- Variant scoping --------------------------------------------------------

def test_variant_scopes_lookups(seeded, client):
    _raw(seeded, variant="holofoil", market=120.0)
    _raw(seeded, variant="reverseHolofoil", market=20.0)
    _graded(seeded, grade=10.0, variant="holofoil", market=1200.0)
    _graded(seeded, grade=10.0, variant="reverseHolofoil", market=40.0)

    body = _tradeup(client, variant="holofoil").json()

    assert body["grade_leg"]["gross"] == 1200.0  # not the 40 reverse
    assert body["market_reference"] == 120.0