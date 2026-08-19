"""Tests for SealedDealEngine — read-only flip-edge for sealed products (Phase 05c)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from cardplatform.config import Settings
from cardplatform.sealed.engine import SealedDealEngine, SealedDealAssessment
from cardplatform.sealed.provider import SealedListing, SealedSoldComp


@dataclass
class FakeProvider:
    name: str = "fake"
    def __init__(self, listings=(), comps=()):
        self._listings = list(listings)
        self._comps = list(comps)
    def fetch_listings_by_query(self, query):
        return list(self._listings)
    def fetch_sold_listings_by_query(self, query, limit=3):
        return list(self._comps)


def _listing(id_, price, listing_type="fixed_price"):
    return SealedListing(query="q", listing_id=str(id_), source="ebay",
                         title=f"L{id_}", price=price, currency="USD",
                         listing_type=listing_type, url=f"u{id_}")


def _comp(id_, price):
    return SealedSoldComp(query="q", listing_id=str(id_), price=price, currency="USD",
                           title=f"C{id_}", url=f"cu{id_}", sold_at=None, source="ebay")


def _engine(listings=(), comps=(), **overrides):
    kw = dict(sealed_flip_min_abs=20.0, sealed_flip_min_pct=0.05, sealed_sold_comp_limit=10)
    kw.update(overrides)
    settings = Settings(**kw)
    return SealedDealEngine(FakeProvider(listings, comps), settings=settings)


def test_sealed_market_is_median_of_sold_comps():
    e = _engine(comps=[_comp(1, 100.0), _comp(2, 120.0), _comp(3, 200.0)])  # median 120
    r = e.assess("q", limit=20)
    assert r.sealed_market is not None and r.sealed_market.price == 120.0


def test_flip_edge_is_market_minus_listing_price():
    e = _engine(listings=[_listing(1, 90.0)], comps=[_comp(1, 120.0)])  # market 120
    r = e.assess("q", limit=20)
    a = r.assessments[0]
    assert a.flip_edge == 30.0
    assert a.is_flip is True  # 30 >= 20 abs and >= 0.05*120=6


def test_no_sold_comps_means_sealed_market_none_and_all_flip_edges_null():
    e = _engine(listings=[_listing(1, 90.0)], comps=[])
    r = e.assess("q", limit=20)
    assert r.sealed_market is None
    assert r.assessments[0].flip_edge is None  # never a fabricated edge
    assert r.assessments[0].is_flip is False
    assert r.comps_count == 0


def test_listing_missing_price_has_null_flip_edge_never_zero():
    e = _engine(listings=[SealedListing(query="q", listing_id="1", source="ebay",
                                         title="L1", price=None, currency="USD")],
                comps=[_comp(1, 120.0)])
    r = e.assess("q", limit=20)
    a = r.assessments[0]
    assert a.flip_edge is None  # missing listing price -> null edge, never $0
    assert a.is_flip is False


def test_deals_ranked_by_flip_edge_desc_nulls_last():
    e = _engine(listings=[_listing(1, 100.0), _listing(2, 80.0), _listing(3, 130.0)],
                comps=[_comp(1, 120.0)])  # market 120 -> edges 20, 40, -10
    r = e.assess("q", limit=20)
    scores = [a.flip_edge for a in r.assessments]
    assert scores == [40.0, 20.0, -10.0]  # desc


def test_is_flip_respects_both_abs_and_pct_thresholds():
    # flip_edge = 25, market = 120 -> pct threshold = 6; 25>=6 and 25>=20 -> flip
    e = _engine(listings=[_listing(1, 95.0)], comps=[_comp(1, 120.0)])
    assert _engine_assess_is_flip(e) is True
    # Raise abs threshold above the edge -> not a flip despite pct passing
    e2 = _engine(listings=[_listing(1, 95.0)], comps=[_comp(1, 120.0)], sealed_flip_min_abs=30.0)
    assert _engine_assess_is_flip(e2) is False


def _engine_assess_is_flip(engine):
    return engine.assess("q", limit=20).assessments[0].is_flip


def test_empty_query_listings_returns_empty_assessments_never_raises():
    e = _engine(listings=[], comps=[_comp(1, 120.0)])
    r = e.assess("q", limit=20)
    assert r.assessments == []
    assert r.listings_count == 0


def test_deal_score_is_flip_edge_or_null():
    e = _engine(listings=[_listing(1, 90.0)], comps=[_comp(1, 120.0)])
    a = e.assess("q", limit=20).assessments[0]
    assert a.deal_score == 30.0
    e2 = _engine(listings=[_listing(1, 90.0)], comps=[])
    a2 = e2.assess("q", limit=20).assessments[0]
    assert a2.deal_score is None  # nulls last