"""T2: SealedScanLogService — log a sealed purchase from a catalog row (Phase B).

Uses the shared `db` fixture (a real SQLite session backed by create_all, so
the sealed_products + sealed_purchases tables auto-provision). Seeds a known
catalog row via SealedCatalogService.ensure_seed(SEALED_PRODUCTS) so a real slug
exists. No network, no API.
"""
from __future__ import annotations

import pytest

from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.scan_log import SealedScanLogService
from cardplatform.sealed.seed_data import SEALED_PRODUCTS


def _seed(db) -> None:
    SealedCatalogService(db).ensure_seed(SEALED_PRODUCTS)


def test_log_from_catalog_uses_product_name_and_type(db):
    _seed(db)
    svc = SealedScanLogService(db)

    purchase = svc.log_from_catalog("base-booster-pack", cost_per_unit=4.99)

    product = SealedCatalogService(db).get("base-booster-pack")
    assert purchase.query == product.name
    assert purchase.product_type == product.product_type
    # Defaults: quantity 1, bought_at populated by the column default (utcnow).
    assert purchase.quantity == 1
    assert purchase.bought_at is not None


def test_log_from_catalog_raises_lookup_error_on_unknown_slug(db):
    _seed(db)
    svc = SealedScanLogService(db)

    with pytest.raises(LookupError):
        svc.log_from_catalog("does-not-exist", cost_per_unit=10.0)


def test_log_from_catalog_respects_quantity_and_cost(db):
    _seed(db)
    svc = SealedScanLogService(db)

    purchase = svc.log_from_catalog(
        "base-booster-box", quantity=3, cost_per_unit=120.0
    )

    assert purchase.quantity == 3
    assert purchase.cost_per_unit == 120.0


def test_log_from_catalog_honest_none_for_optional_fields(db):
    """A purchase with no source/listing_url/notes stores None — never an empty
    fabrication."""
    _seed(db)
    svc = SealedScanLogService(db)

    purchase = svc.log_from_catalog("base-booster-pack", cost_per_unit=4.99)

    assert purchase.source is None
    assert purchase.listing_url is None
    assert purchase.notes is None