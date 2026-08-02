"""Phase 3c Task 1: Watch/ListingSnapshot/AlertEvent/PushSubscription schema.

Pins the contract for the four new tables that underpin the alerts/watchlist
feature. New tables belong to `Base.metadata.create_all` (NOT to the
ALTER-only `run_migrations` helper), so these tests exercise the
`create_all` + `run_migrations` pair the same way `cli.py` and `api.py` do
at startup.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from cardplatform.config import Settings
from cardplatform.db.migrations import run_migrations
from cardplatform.db.models import (
    AlertEvent,
    Base,
    Card,
    CardSet,
    ListingSnapshot,
    PushSubscription,
    Watch,
)
from cardplatform.db.session import Database

# The real populated DB lives at <repo_root>/data/cardplatform.sqlite3 (not
# backend/data/). Used by test_existing_data_preserved to copy a live DB and
# prove the new-table migration does not touch existing rows.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_DB = _REPO_ROOT / "data" / "cardplatform.sqlite3"


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _seed_card(db) -> None:
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


# --- new tables are created by create_all + run_migrations -------------------


def test_new_tables_created(tmp_path):
    """A fresh temp DB built via create_all + run_migrations has all four tables."""
    database = Database(Settings(data_dir=tmp_path))
    Base.metadata.create_all(database.engine)
    run_migrations(database.engine)

    tables = _tables(database.engine)
    assert "watchlist" in tables
    assert "listing_snapshots" in tables
    assert "alert_events" in tables
    assert "push_subscriptions" in tables


# --- models round-trip with tz-aware datetimes and documented defaults --------

_AWARE = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_models_roundtrip(tmp_path):
    """One row per new table round-trips; defaults and tz-awareness hold."""
    database = Database(Settings(data_dir=tmp_path))
    Base.metadata.create_all(database.engine)
    run_migrations(database.engine)

    with database.session() as s:
        _seed_card(s)

        watch = Watch(
            card_id="base1-4",
            alert_type="price_drop",
            target_price=50.0,
            drop_at=_AWARE,
        )
        s.add(watch)

        listing = ListingSnapshot(
            card_id="base1-4",
            variant="holofoil",
            source="ebay",
            listing_id="ebay-123",
            price=42.0,
            auction_end_at=_AWARE,
            fetched_at=_AWARE,
        )
        s.add(listing)

        alert = AlertEvent(
            card_id="base1-4",
            alert_type="price_drop",
            message="Charizard dropped below $50",
            created_at=_AWARE,
        )
        s.add(alert)

        sub = PushSubscription(
            endpoint="https://push.example/abc",
            p256dh="p256dh-key",
            auth="auth-secret",
            created_at=_AWARE,
        )
        s.add(sub)
        s.commit()
        s.expunge_all()

        # Watch defaults
        w = s.query(Watch).one()
        assert w.active is True
        assert w.auction_window_min == 30
        assert w.created_at.tzinfo is not None
        assert w.drop_at == _AWARE
        assert w.drop_at.tzinfo is not None

        # ListingSnapshot: empty-string sentinel for source_updated_at
        ls = s.query(ListingSnapshot).one()
        assert ls.source_updated_at == ""
        assert ls.fetched_at.tzinfo is not None
        assert ls.auction_end_at == _AWARE

        # AlertEvent delivery defaults
        ae = s.query(AlertEvent).one()
        assert ae.delivered_inapp is True
        assert ae.delivered_push is False
        assert ae.delivered_email is False
        assert ae.read_at is None
        assert ae.created_at == _AWARE
        assert ae.created_at.tzinfo is not None

        # PushSubscription
        ps = s.query(PushSubscription).one()
        assert ps.endpoint == "https://push.example/abc"
        assert ps.created_at == _AWARE
        assert ps.created_at.tzinfo is not None

        # Duplicate endpoint must collide via the unique constraint.
        s.add(
            PushSubscription(
                endpoint="https://push.example/abc",
                p256dh="p256dh-key-2",
                auth="auth-secret-2",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


# --- existing data is preserved when the schema grows -------------------------


@pytest.mark.skipif(
    not _REAL_DB.exists(),
    reason=f"real DB not found at {_REAL_DB}",
)
def test_existing_data_preserved(tmp_path):
    """create_all + run_migrations on a copy of the real DB preserves rows.

    Copies the populated production DB to a temp path, runs the same
    create_all + run_migrations pair that startup runs, and asserts that
    scan_logs and cards row counts are unchanged and the four new tables
    exist and are empty.
    """
    tmp_db = tmp_path / "cardplatform.sqlite3"
    shutil.copy(_REAL_DB, tmp_db)

    database = Database(Settings(data_dir=tmp_path))
    Base.metadata.create_all(database.engine)
    run_migrations(database.engine)

    with database.engine.connect() as conn:
        before_scans = conn.execute(text("SELECT COUNT(*) FROM scan_logs")).scalar()
        before_cards = conn.execute(text("SELECT COUNT(*) FROM cards")).scalar()

    # Re-run to mirror repeated startup behavior; counts must not move.
    Base.metadata.create_all(database.engine)
    run_migrations(database.engine)

    with database.engine.connect() as conn:
        after_scans = conn.execute(text("SELECT COUNT(*) FROM scan_logs")).scalar()
        after_cards = conn.execute(text("SELECT COUNT(*) FROM cards")).scalar()
        watch_count = conn.execute(text("SELECT COUNT(*) FROM watchlist")).scalar()
        listing_count = conn.execute(text("SELECT COUNT(*) FROM listing_snapshots")).scalar()
        alert_count = conn.execute(text("SELECT COUNT(*) FROM alert_events")).scalar()
        push_count = conn.execute(text("SELECT COUNT(*) FROM push_subscriptions")).scalar()

    assert before_scans == after_scans
    assert before_cards == after_cards

    tables = _tables(database.engine)
    assert {"watchlist", "listing_snapshots", "alert_events", "push_subscriptions"} <= tables
    assert watch_count == 0
    assert listing_count == 0
    assert alert_count == 0
    assert push_count == 0