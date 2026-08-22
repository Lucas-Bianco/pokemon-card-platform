"""T1: SealedCatalogService — browse/search + idempotent seed (Phase A, slice A1).

Uses the shared `db` fixture (a real SQLite session backed by create_all, so the
new sealed_products table auto-provisions). No network, no API.
"""
from __future__ import annotations

import pytest

from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.seed_data import SEALED_PRODUCTS


def _svc(db):
    return SealedCatalogService(db)


def test_ensure_seed_inserts_all_then_idempotent(db):
    svc = _svc(db)
    assert svc.count() == 0  # empty table on a fresh tmp DB

    n1 = svc.ensure_seed(SEALED_PRODUCTS)
    assert n1 == len(SEALED_PRODUCTS)
    assert svc.count() == len(SEALED_PRODUCTS)

    # Re-run against a populated table -> 0 inserted (skip-existing, never dup).
    n2 = svc.ensure_seed(SEALED_PRODUCTS)
    assert n2 == 0
    assert svc.count() == len(SEALED_PRODUCTS)


def test_ensure_seed_skips_existing_without_clobbering_partial(db):
    """If the table already has some slugs, only the missing ones are inserted."""
    svc = _svc(db)
    # Seed just the first two rows manually.
    svc.ensure_seed(SEALED_PRODUCTS[:2])
    assert svc.count() == 2

    n = svc.ensure_seed(SEALED_PRODUCTS)
    assert n == len(SEALED_PRODUCTS) - 2
    assert svc.count() == len(SEALED_PRODUCTS)


def test_search_lowercase_substring_matches_name(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    rows = svc.search(query="booster pack")
    assert rows  # non-empty
    # Every hit contains "booster pack" in the name (case-insensitive).
    assert all("booster pack" in r.name.lower() for r in rows)


def test_search_matches_era(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    rows = svc.search(query="scarlet & violet")
    assert rows
    assert all(r.era == "Scarlet & Violet" for r in rows)


def test_search_type_and_status_filters_compose(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    rows = svc.search(product_type="etb", print_status="in_print")
    assert rows
    assert all(r.product_type == "etb" and r.print_status == "in_print" for r in rows)


def test_search_no_query_newest_first(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    rows = svc.search()
    # Newest released_at first; the most recent set in the seed is 2024-03-22.
    assert rows[0].released_at == "2024-03-22"


def test_get_raises_lookup_error_on_unknown(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    with pytest.raises(LookupError):
        svc.get("does-not-exist")


def test_get_returns_known(db):
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    p = svc.get("base-booster-pack")
    assert p.name == "Base Set Booster Pack"
    assert p.product_type == "booster_pack"


def test_honest_null_msrp_preserved(db):
    """Booster boxes have no MSRP in the seed -> stored as None, never 0."""
    svc = _svc(db)
    svc.ensure_seed(SEALED_PRODUCTS)
    box = svc.get("base-booster-box")
    assert box.msrp is None