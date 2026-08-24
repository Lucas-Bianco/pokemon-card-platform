"""T5: POST /alerts/check — the on-demand pull endpoint (roadmap row 20).

Pins the honest *pull* contract at the boundary: the endpoint runs one
AlertEngine tick against currently-known listings/snapshots and returns the
freshly-fired events. Reuses the exact engine the startup poll loop uses, so a
pull and a poll can never disagree. It never promises a notification — the
in-app AlertEvent row is the always-available floor.

Listings are seeded directly as ListingSnapshot rows (no network): the route's
real ListingsService reads them via lowest_price, exactly as the poll loop
does, so the price_target eval is exercised for real through the HTTP layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import AlertEvent, Card, CardSet, ListingSnapshot, Watch


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


def _listing(db, *, price, variant="normal", listing_id="L1",
             source="ebay", fetched_at=None):
    db.add(ListingSnapshot(
        card_id="base1-4",
        variant=variant,
        source=source,
        listing_id=listing_id,
        price=price,
        currency="USD",
        listing_type="fixed_price",
        source_updated_at="",
        fetched_at=fetched_at or datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    ))
    db.commit()


def _watch(db, **kw) -> Watch:
    defaults = dict(
        card_id="base1-4",
        subject_label=None,
        variant="normal",
        alert_type="price_target",
        target_price=40.0,
        drop_at=None,
        lead_time_min=None,
        auction_window_min=30,
        active=True,
        last_seen_listing_ids=None,
        last_fired_at=None,
    )
    defaults.update(kw)
    w = Watch(**defaults)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def test_check_fires_price_target_when_listing_at_or_below_target(seeded, client):
    """A price_target watch + a listing priced under the target -> one event
    fired, returned in the response, and persisted as an AlertEvent row."""
    _watch(seeded, target_price=40.0)
    _listing(seeded, price=38.0)

    body = client.post("/alerts/check").json()

    assert body["fired"] == 1
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["alert_type"] == "price_target"
    assert "hit target" in ev["message"]
    # Persisted — the in-app row is the always-available floor.
    rows = seeded.query(AlertEvent).filter(AlertEvent.alert_type == "price_target").all()
    assert len(rows) == 1
    assert rows[0].id == ev["id"]


def test_check_returns_zero_fired_and_empty_events_when_nothing_triggers(seeded, client):
    """No watch -> nothing fires; the response is honest (0, []), never a
    fabricated event."""
    body = client.post("/alerts/check").json()
    assert body["fired"] == 0
    assert body["events"] == []


def test_check_does_not_fire_when_listing_above_target(seeded, client):
    """Listing priced ABOVE the target re-arms; no event fires."""
    _watch(seeded, target_price=40.0)
    _listing(seeded, price=50.0)

    body = client.post("/alerts/check").json()
    assert body["fired"] == 0
    assert body["events"] == []


def test_check_respects_cooldown_on_repeat_pull(seeded, client):
    """A second pull within the cooldown fires 0 — the watch's last_fired_at
    was set by the first. The first event is not duplicated."""
    _watch(seeded, target_price=40.0)
    _listing(seeded, price=38.0)

    first = client.post("/alerts/check").json()
    assert first["fired"] == 1

    second = client.post("/alerts/check").json()
    assert second["fired"] == 0
    assert second["events"] == []

    # Still exactly one persisted event.
    rows = seeded.query(AlertEvent).filter(AlertEvent.alert_type == "price_target").all()
    assert len(rows) == 1


def test_check_never_raises_without_listings_key(seeded, client):
    """No ListingSnapshot rows (and no listings_api_key in settings) -> the
    provider returns [], lowest_price is None, the watch does not fire, and the
    endpoint returns 200 with (0, []) — never a 500. The honest pull model."""
    _watch(seeded, target_price=40.0)
    # No listing seeded.

    response = client.post("/alerts/check")
    assert response.status_code == 200
    body = response.json()
    assert body["fired"] == 0
    assert body["events"] == []


def test_check_only_returns_events_fired_this_pull(seeded, client):
    """A pre-existing AlertEvent (from a prior tick) must NOT be returned as
    part of this pull — only rows with id > the pre-check high-water mark."""
    _watch(seeded, target_price=40.0)
    _listing(seeded, price=38.0)

    # First pull fires one.
    client.post("/alerts/check")
    prior_count = seeded.query(AlertEvent).count()
    assert prior_count == 1

    # Manually add an unrelated older event so there are pre-existing rows,
    # then pull again within cooldown (fires 0) -> events must be empty even
    # though AlertEvent rows exist.
    seeded.add(AlertEvent(
        card_id="base1-4", alert_type="restock", message="old",
        context=None, delivered_inapp=True, delivered_push=False,
        delivered_email=False, read_at=None,
        created_at=datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc),
    ))
    seeded.commit()

    body = client.post("/alerts/check").json()
    assert body["fired"] == 0
    assert body["events"] == []  # the older row is not surfaced as "this pull"


def test_check_invariants_response_shape(seeded, client):
    """The response carries the two fields the UI branches on, with the right
    types, even on an empty pull."""
    body = client.post("/alerts/check").json()
    assert isinstance(body["fired"], int)
    assert isinstance(body["events"], list)