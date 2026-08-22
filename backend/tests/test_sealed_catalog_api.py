"""T2: GET /sealed/products + GET /sealed/products/{slug} (Phase A, slice A1).

Overrides `get_session` with the shared `db` fixture (a real tmp SQLite session)
and seeds the catalog via the service's own `ensure_seed` (not via the
`_get_database` startup hook, which would touch the real data file). No network.
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


def test_sealed_products_returns_seeded(client):
    r = client.get("/sealed/products")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(SEALED_PRODUCTS)
    assert body["product_type"] is None
    assert body["print_status"] is None
    # Newest first: 2024-03-22 (Temporal Forces) leads.
    assert body["products"][0]["released_at"] == "2024-03-22"
    slugs = {p["slug"] for p in body["products"]}
    assert "base-booster-pack" in slugs


def test_sealed_products_filter_by_type(client):
    r = client.get("/sealed/products", params={"type": "etb"})
    assert r.status_code == 200
    body = r.json()
    assert body["product_type"] == "etb"
    assert body["count"] > 0
    assert all(p["product_type"] == "etb" for p in body["products"])


def test_sealed_products_filter_by_status(client):
    r = client.get("/sealed/products", params={"status": "in_print"})
    assert r.status_code == 200
    body = r.json()
    assert body["print_status"] == "in_print"
    assert all(p["print_status"] == "in_print" for p in body["products"])


def test_sealed_products_unknown_type_422(client):
    assert client.get("/sealed/products", params={"type": "mega-tin"}).status_code == 422


def test_sealed_products_unknown_status_422(client):
    assert client.get("/sealed/products", params={"status": "limited"}).status_code == 422


def test_sealed_products_empty_q_lists_all(client):
    r = client.get("/sealed/products", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["count"] == len(SEALED_PRODUCTS)


def test_sealed_products_query_matches_substring(client):
    r = client.get("/sealed/products", params={"q": "elite trainer"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert all("elite trainer" in p["name"].lower() for p in body["products"])


def test_sealed_products_limit_clamp_low_422(client):
    assert client.get("/sealed/products", params={"limit": 0}).status_code == 422


def test_sealed_products_limit_clamp_high_422(client):
    assert client.get("/sealed/products", params={"limit": 201}).status_code == 422


def test_sealed_product_by_slug(client):
    r = client.get("/sealed/products/base-booster-pack")
    assert r.status_code == 200
    p = r.json()
    assert p["slug"] == "base-booster-pack"
    assert p["name"] == "Base Set Booster Pack"
    assert p["msrp"] is None  # honest null, never 0


def test_sealed_product_unknown_slug_404(client):
    assert client.get("/sealed/products/does-not-exist").status_code == 404


def test_sealed_product_msrp_honest_nonzero(client):
    """ETB has a known MSRP -> surfaces as the real number, never fabricated."""
    r = client.get("/sealed/products/scarlet-violet-elite-trainer-box")
    assert r.status_code == 200
    assert r.json()["msrp"] == 39.99


def test_sealed_products_count_echoes_filter(client):
    """`count` is the returned page size, echoed with the active filter."""
    r = client.get("/sealed/products", params={"type": "booster_box"})
    body = r.json()
    assert body["count"] == len(body["products"])
    assert body["product_type"] == "booster_box"