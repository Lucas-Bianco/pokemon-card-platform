"""Phase B: POST /sealed/ledger/from-catalog — log a sealed buy straight from a
catalog row by slug.

Mirrors test_sealed_catalog_api.py: override `get_session` with the shared `db`
fixture and seed the catalog via the service's own `ensure_seed`. No network, no
provider (the scan-log service resolves name + product_type from the catalog and
writes a SealedPurchase — it never calls eBay). Unknown slug -> 404; bad
quantity/cost -> 422 (Pydantic bounds, before the service runs).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import app, get_session
from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.seed_data import SEALED_PRODUCTS


@pytest.fixture
def seeded(db):
    SealedCatalogService(db).ensure_seed(SEALED_PRODUCTS)
    return db


@pytest.fixture
def client(seeded):
    app.dependency_overrides[get_session] = lambda: seeded
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_from_catalog_logs_purchase(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={
            "slug": "scarlet-violet-elite-trainer-box",
            "quantity": 2,
            "cost_per_unit": 39.99,
            "source": "Pokémon Center",
        },
    )
    assert r.status_code == 201
    body = r.json()
    # Name + product_type are resolved server-side from the catalog, not sent by
    # the client. The query carries the product name (the ledger's search key).
    assert body["query"] == "Scarlet & Violet Elite Trainer Box"
    assert body["product_type"] == "etb"
    assert body["quantity"] == 2
    assert body["cost_per_unit"] == 39.99
    assert body["source"] == "Pokémon Center"
    assert body["id"] > 0


def test_from_catalog_defaults_quantity_to_one(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"slug": "base-booster-pack", "cost_per_unit": 5.00},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["quantity"] == 1
    assert body["product_type"] == "booster_pack"
    # A product with no MSRP still logs fine — MSRP is a catalog concern, not a
    # purchase concern; the purchase only records what the user actually paid.
    assert body["query"] == "Base Set Booster Pack"


def test_from_catalog_unknown_slug_404(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"slug": "does-not-exist", "cost_per_unit": 10.00},
    )
    assert r.status_code == 404


def test_from_catalog_quantity_zero_422(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"slug": "base-booster-pack", "quantity": 0, "cost_per_unit": 5.00},
    )
    assert r.status_code == 422


def test_from_catalog_negative_cost_422(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"slug": "base-booster-pack", "cost_per_unit": -1.00},
    )
    assert r.status_code == 422


def test_from_catalog_missing_cost_422(client):
    # cost_per_unit has no default -> a body omitting it is a clean 422, not a 500.
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"slug": "base-booster-pack"},
    )
    assert r.status_code == 422


def test_from_catalog_missing_slug_422(client):
    r = client.post(
        "/sealed/ledger/from-catalog",
        json={"cost_per_unit": 5.00},
    )
    assert r.status_code == 422