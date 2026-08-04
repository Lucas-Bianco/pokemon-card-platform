"""T4: AlertEngine — `_eval_deal` deals alert with baseline-dedupe.

Mirrors test_alert_engine.py: a temp SQLite session (the `db` fixture), a
_FakeDealEngine (no network), and direct Watch/Card/AlertEvent rows. Time is
injected via the `clock` parameter. AlertEvents are real rows.

The deal alert reuses `_eval_new_listing`'s baseline-dedupe pattern: the first
poll establishes the baseline (never fires); subsequent polls fire only for
listing ids that are deals AND not yet in the baseline. The baseline always
advances so a listing that stops being a deal cannot re-fire. A missing
deal_engine is a silent no-op.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cardplatform.alerts.engine import AlertEngine
from cardplatform.db.models import AlertEvent, Card, CardSet, Watch


T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class Clock:
    """A controllable UTC clock: injectable via the engine's `clock` param."""

    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> datetime:
        self.t = self.t + timedelta(**kw)
        return self.t


class _FakeDealEngine:
    """Stand-in for DealEngine.assess. No network; settable return values.

    `assess` returns the list of assessments pinned via the constructor or via
    `set_assessments`. Each assessment is a SimpleNamespace carrying the fields
    `_eval_deal` reads.
    """

    def __init__(self, assessments=None):
        self._assessments = list(assessments or [])

    def assess(self, card_id, variant):
        return list(self._assessments)

    def set_assessments(self, assessments):
        self._assessments = list(assessments)


def _assess(
    listing_id,
    is_rip=False,
    is_flip=False,
    listing_price=10.0,
    currency="USD",
    url="https://ebay.com/itm/1",
    condition="Near Mint",
    rip_edge=None,
    flip_edge_to_10=None,
    deal_score=None,
    raw_market=None,
):
    return SimpleNamespace(
        listing_id=listing_id,
        is_rip=is_rip,
        is_flip=is_flip,
        listing_price=listing_price,
        currency=currency,
        url=url,
        condition=condition,
        rip_edge=rip_edge,
        flip_edge_to_10=flip_edge_to_10,
        deal_score=deal_score,
        raw_market=raw_market,
    )


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def _watch(db, **kw) -> Watch:
    """Insert a Watch with sensible defaults; commit and return."""
    defaults = dict(
        card_id="base1-4",
        subject_label=None,
        variant="normal",
        alert_type="deal",
        target_price=None,
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
    return w


def _events(db):
    return db.query(AlertEvent).order_by(AlertEvent.id).all()


# --------------------------------------------------------------- deal


def test_deal_no_fire_first_poll_establishes_baseline(seeded):
    """last_seen None, two deal assessments (one rip, one flip) -> 0 events
    (baseline), last_seen == JSON of both deal listing ids."""
    deals = [
        _assess("a", is_rip=True, rip_edge=20.0, deal_score=20.0),
        _assess("b", is_flip=True, flip_edge_to_10=95.0, deal_score=95.0),
    ]
    fake = _FakeDealEngine(deals)
    w = _watch(seeded, alert_type="deal")
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=fake)

    n = eng.check_alerts()

    assert n == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert set(json.loads(w.last_seen_listing_ids)) == {"a", "b"}


def test_deal_fires_only_for_new_deal_listings(seeded):
    """baseline already has id 'a'; fake returns is_rip assessments for 'a' and
    'b' -> fires exactly 1 event, the event's context contains 'b' (the new id),
    alert_type == 'deal'."""
    deals = [
        _assess("a", is_rip=True, rip_edge=20.0, deal_score=20.0),
        _assess("b", is_rip=True, rip_edge=15.0, deal_score=15.0),
    ]
    fake = _FakeDealEngine(deals)
    w = _watch(seeded, alert_type="deal", last_seen_listing_ids=json.dumps(["a"]))
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=fake)

    n = eng.check_alerts()

    assert n == 1
    evs = _events(seeded)
    assert len(evs) == 1
    assert evs[0].alert_type == "deal"
    ctx = json.loads(evs[0].context)
    assert ctx["listing_id"] == "b"
    seeded.refresh(w)
    assert set(json.loads(w.last_seen_listing_ids)) == {"a", "b"}


def test_deal_does_not_fire_for_non_deal_listings(seeded):
    """fake returns one assessment with is_rip=False, is_flip=False -> after
    baseline established, a second poll fires 0 and no events."""
    deals = [_assess("a", is_rip=False, is_flip=False)]
    fake = _FakeDealEngine(deals)
    w = _watch(seeded, alert_type="deal")
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=fake)

    # Poll 1: baseline established (curr_ids is empty since the assessment is
    # neither rip nor flip -> not in deal_map). 0 events.
    assert eng.check_alerts() == 0
    # Poll 2: still no deals. 0 events.
    assert eng.check_alerts() == 0
    assert _events(seeded) == []


def test_deal_baseline_advances_so_removed_deal_does_not_refire(seeded):
    """fake returns only 'a' (is_rip). Poll 1 (baseline=[]) fires 1; poll 2
    (baseline=['a'], 'a' still present) fires 0; total events == 1."""
    deals = [_assess("a", is_rip=True, rip_edge=20.0, deal_score=20.0)]
    fake = _FakeDealEngine(deals)
    w = _watch(seeded, alert_type="deal", last_seen_listing_ids=json.dumps([]))
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=fake)

    # Poll 1: prev_ids is the empty set (not None), curr {'a'} -> new_ids {'a'}.
    assert eng.check_alerts() == 1
    # Poll 2: baseline is now ['a'], 'a' still present -> no new ids -> 0.
    assert eng.check_alerts() == 0
    assert len(_events(seeded)) == 1


def test_deal_no_deal_engine_is_no_op(seeded):
    """construct AlertEngine(..., deal_engine=None) with a deal watch -> 0 events,
    no raise."""
    w = _watch(seeded, alert_type="deal")
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=None)

    n = eng.check_alerts()

    assert n == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert w.last_seen_listing_ids is None


def test_deal_flip_message_when_flip_dominates(seeded):
    """a new is_flip assessment with flip_edge_to_10=95.0, is_rip=False,
    rip_edge=None -> the fired event's message contains 'flip' (case-insensitive)
    or '95'."""
    deals = [_assess("b", is_flip=True, flip_edge_to_10=95.0, is_rip=False,
                     rip_edge=None, deal_score=95.0)]
    fake = _FakeDealEngine(deals)
    w = _watch(seeded, alert_type="deal", last_seen_listing_ids=json.dumps([]))
    eng = AlertEngine(seeded, clock=Clock(), deal_engine=fake)

    n = eng.check_alerts()

    assert n == 1
    evs = _events(seeded)
    assert len(evs) == 1
    msg = evs[0].message.lower()
    assert "flip" in msg or "95" in msg