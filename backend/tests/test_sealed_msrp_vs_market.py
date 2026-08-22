"""Tests for MsrpVsMarketService (Phase C, roadmap row 09).

Compares a catalog product's curated MSRP against the live eBay sold-comps
median, with the SAME honest unavailable/empty flags /sealed/sold-comps uses.
No network: a fake provider stubs `fetch_sold_listings_by_query`. The catalog is
seeded with the in-repo SEALED_PRODUCTS so real slugs (a known-MSRP ETB + a
null-MSRP booster box) drive the cases.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cardplatform.config import Settings
from cardplatform.sealed.msrp_vs_market import MsrpVsMarketService
from cardplatform.sealed.provider import SealedSoldComp
from cardplatform.sealed.seed_data import SEALED_PRODUCTS


class _FakeProvider:
    """Minimal SealedListingsProvider stand-in: returns canned sold comps per call."""

    name = "ebay"

    def __init__(self, comps, raise_on_call=False):
        self._comps = comps
        self._raise = raise_on_call

    def fetch_listings_by_query(self, query):
        return []

    def fetch_sold_listings_by_query(self, query, limit=6):
        if self._raise:
            raise RuntimeError("boom")
        return list(self._comps)


def _comp(price=118.0, listing_id="a"):
    return SealedSoldComp(
        query="x",
        listing_id=listing_id,
        price=price,
        currency="USD",
        url="https://ebay.example/x",
        condition="New",
        sold_at=datetime(2026, 7, 30, 18, 30, tzinfo=timezone.utc),
        title="x",
        source="ebay",
    )


@pytest.fixture
def seeded_db(db):
    from cardplatform.sealed.catalog_service import SealedCatalogService
    SealedCatalogService(db).ensure_seed(SEALED_PRODUCTS)
    return db


def _settings(tmp_path, key="an-app-id"):
    return Settings(data_dir=tmp_path, listings_api_key=key, sealed_sold_comp_limit=6)


# --- cases ---

def test_msrp_and_comps_present_delta_is_msrp_minus_median(seeded_db, tmp_path):
    """msrp + comps present -> delta == msrp - median, unavailable False, empty False."""
    comps = [_comp(118.0, "a"), _comp(121.0, "b"), _comp(119.0, "c")]  # median 119.0
    svc = MsrpVsMarketService(seeded_db, _settings(tmp_path), _FakeProvider(comps))

    out = svc.compare("sword-shield-elite-trainer-box")  # msrp 39.99
    assert out["slug"] == "sword-shield-elite-trainer-box"
    assert out["msrp"] == 39.99
    assert out["msrp_currency"] == "USD"
    assert out["market_median"] == 119.0
    assert out["market_source"] == "ebay"
    assert out["market_source_updated_at"] is None
    assert out["sold_comps_count"] == 3
    assert out["delta"] == pytest.approx(39.99 - 119.0)
    assert out["unavailable"] is False
    assert out["empty"] is False


def test_null_msrp_booster_box_delta_none(seeded_db, tmp_path):
    """null msrp (booster box) -> delta None (NOT 0), msrp None."""
    comps = [_comp(200.0, "a"), _comp(210.0, "b")]  # median 205.0
    svc = MsrpVsMarketService(seeded_db, _settings(tmp_path), _FakeProvider(comps))

    out = svc.compare("base-booster-box")  # msrp None
    assert out["msrp"] is None
    assert out["msrp_currency"] == "USD"
    assert out["market_median"] == 205.0
    assert out["delta"] is None  # never a fabricated 0
    assert out["unavailable"] is False
    assert out["empty"] is False


def test_no_comps_empty_flag_and_null_median(seeded_db, tmp_path):
    """key set but provider returns [] -> market_median None, empty True, delta None."""
    svc = MsrpVsMarketService(seeded_db, _settings(tmp_path), _FakeProvider([]))

    out = svc.compare("sword-shield-elite-trainer-box")
    assert out["market_median"] is None  # never 0
    assert out["market_source"] is None
    assert out["market_source_updated_at"] is None
    assert out["sold_comps_count"] == 0
    assert out["delta"] is None  # msrp present but no market -> no delta
    assert out["unavailable"] is False
    assert out["empty"] is True


def test_provider_unavailable_no_key(seeded_db, tmp_path):
    """No listings_api_key -> unavailable True, market_median None (honest, not $0)."""
    # Provider returns [] (as the real EbayListingsProvider does with no key), but
    # the unavailable flag is driven by the key being unset, not by the [] itself.
    svc = MsrpVsMarketService(
        seeded_db, _settings(tmp_path, key=None), _FakeProvider([])
    )

    out = svc.compare("sword-shield-elite-trainer-box")
    assert out["unavailable"] is True
    assert out["empty"] is False  # empty only counts when key is set
    assert out["market_median"] is None
    assert out["market_source"] is None
    assert out["sold_comps_count"] == 0
    assert out["delta"] is None


def test_provider_failure_degrades_to_empty_not_raise(seeded_db, tmp_path):
    """A raising provider degrades to [] — the service never raises out of it."""
    svc = MsrpVsMarketService(
        seeded_db, _settings(tmp_path), _FakeProvider([], raise_on_call=True)
    )

    out = svc.compare("sword-shield-elite-trainer-box")
    # Key is set, provider blew up -> honest empty, not an exception.
    assert out["unavailable"] is False
    assert out["empty"] is True
    assert out["market_median"] is None
    assert out["sold_comps_count"] == 0
    assert out["delta"] is None


def test_unknown_slug_raises_lookup_error(seeded_db, tmp_path):
    """Unknown slug -> LookupError (the route maps this to 404)."""
    svc = MsrpVsMarketService(seeded_db, _settings(tmp_path), _FakeProvider([]))

    with pytest.raises(LookupError):
        svc.compare("does-not-exist-slug")


def test_never_fabricated_zero_market_or_delta(seeded_db, tmp_path):
    """Honesty guard: with no comps, market_median and delta are None, never 0."""
    svc = MsrpVsMarketService(seeded_db, _settings(tmp_path, key=None), _FakeProvider([]))

    out = svc.compare("base-booster-box")  # null msrp AND no comps
    assert out["msrp"] is None
    assert out["market_median"] is None
    assert out["delta"] is None
    assert out["market_median"] != 0
    assert out["delta"] != 0