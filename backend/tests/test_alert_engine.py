"""T3: AlertEngine — five alert types with idempotency, cooldowns, and baselines.

Mirrors test_listings_service.py: a temp SQLite session (the `db` fixture), a
FakeListingsService (no network), and direct Watch/Card/AlertEvent rows. Time
is injected via the `clock` parameter so ticks are deterministic. AlertEvents
are real rows (not fakes) so the auction_ending idempotency query exercises the
model; latest_listings returns SimpleNamespace listing-like objects since the
engine only reads a handful of attributes off them.

Key design decision (see engine.py): restock/new_listing baselines live on
Watch.last_seen_listing_ids, NOT on ListingsService.previous_listing_ids — an
empty fetch inserts no snapshot rows, so it is invisible to the prior-snapshot
diff. The watch's own last_seen is the only field that can observe the
empty -> stocked transition.
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


class FakeListingsService:
    """Stand-in for ListingsService. No network; settable return values.

    refresh_listings ignores its arguments and returns a count (the engine
    ignores the count too). latest_listings/lowest_price return whatever the
    test pins. `raise_on` forces refresh_listings to raise for a card_id, used
    to exercise the never-raise discipline.
    """

    def __init__(self, listings=None, lowest=None, raise_on=None):
        self._listings = list(listings or [])
        self._lowest = lowest
        self._raise_on = raise_on
        self.refresh_calls = []

    def refresh_listings(self, card_id, variant):
        self.refresh_calls.append((card_id, variant))
        if self._raise_on is not None and card_id == self._raise_on:
            raise RuntimeError(f"forced refresh failure for {card_id}")
        return len(self._listings)

    def latest_listings(self, card_id, variant):
        return list(self._listings)

    def lowest_price(self, card_id, variant):
        return self._lowest


class FakeNotifier:
    """Records dispatched events; optionally raises for one watch_id."""

    def __init__(self, raise_on=None):
        self.events = []
        self._raise_on = raise_on

    def dispatch(self, event):
        self.events.append(event)
        if self._raise_on is not None and event.watch_id == self._raise_on:
            raise RuntimeError("forced notifier failure")


def _listing(
    listing_id,
    price=None,
    currency="USD",
    listing_type="fixed_price",
    auction_end_at=None,
    url="https://ebay.com/itm/1",
):
    return SimpleNamespace(
        listing_id=listing_id,
        price=price,
        currency=currency,
        listing_type=listing_type,
        auction_end_at=auction_end_at,
        url=url,
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
        alert_type="restock",
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


# ---------------------------------------------------------------- restock


def test_restock_no_fire_first_poll(seeded):
    """last_seen None, curr={A} -> 0 events (baseline), last_seen == [A]."""
    fake = FakeListingsService(listings=[_listing("A")])
    w = _watch(seeded, alert_type="restock")
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    n = eng.check_alerts()

    assert n == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert json.loads(w.last_seen_listing_ids) == ["A"]


def test_restock_fires_on_empty_to_stocked(seeded):
    """First poll {A} -> baseline. Poll {A} -> 0. Poll [] -> 0 (prev non-empty).
    Poll {B} -> 1 restock event (empty -> stocked)."""
    fake = FakeListingsService(listings=[_listing("A")])
    w = _watch(seeded, alert_type="restock")
    clock = Clock()
    eng = AlertEngine(seeded, listings_service=fake, clock=clock)

    # Poll 1: baseline, last_seen -> [A], 0 events.
    assert eng.check_alerts() == 0
    # Poll 2: still {A}, no change.
    assert eng.check_alerts() == 0
    # Poll 3: empty observation; prev {A} non-empty so no restock; last_seen -> [].
    fake._listings = []
    assert eng.check_alerts() == 0
    seeded.refresh(w)
    assert json.loads(w.last_seen_listing_ids) == []
    # Poll 4: prev [] (empty), curr {B} (stocked) -> restock fires.
    fake._listings = [_listing("B")]
    n = eng.check_alerts()
    assert n == 1
    ev = _events(seeded)
    assert len(ev) == 1
    assert ev[0].alert_type == "restock"
    assert ev[0].message == "Charizard: back in stock"
    ctx = json.loads(ev[0].context)
    assert ctx["listing_ids"] == ["B"]
    assert ctx["source"] == "ebay"


def test_restock_no_fire_when_already_stocked(seeded):
    """prev {A} (non-empty), curr {A,B} (non-empty) -> 0 restock events."""
    w = _watch(seeded, alert_type="restock", last_seen_listing_ids=json.dumps(["A"]))
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    assert eng.check_alerts() == 0
    assert _events(seeded) == []


# ------------------------------------------------------------- new_listing


def test_new_listing_no_fire_first_poll(seeded):
    """last_seen None, curr={A,B} -> 0 events (baseline), last_seen == [A,B]."""
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    w = _watch(seeded, alert_type="new_listing")
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    assert eng.check_alerts() == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert set(json.loads(w.last_seen_listing_ids)) == {"A", "B"}


def test_new_listing_fires_new_ids(seeded):
    """prev {A}, curr {A,B} -> 1 event, context contains B; last_seen -> [A,B]."""
    w = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    n = eng.check_alerts()
    assert n == 1
    ev = _events(seeded)
    assert len(ev) == 1
    assert ev[0].message == "Charizard: 1 new listing(s)"
    ctx = json.loads(ev[0].context)
    assert ctx["new_listing_ids"] == ["B"]
    assert ctx["count"] == 1
    assert ctx["source"] == "ebay"
    seeded.refresh(w)
    assert set(json.loads(w.last_seen_listing_ids)) == {"A", "B"}


# ------------------------------------------------------------ price_target


def test_price_target_fires_below_target_then_rearms(seeded):
    """target 40. >target re-arms; <=target with last_fired None fires; within
    cooldown suppresses; >target re-arms again; <=target fires again."""
    w = _watch(seeded, alert_type="price_target", target_price=40.0)
    clock = Clock()
    eng = AlertEngine(seeded, listings_service=None, clock=clock)

    # tick1: low 50 > target -> re-arm, last_fired None, 0 events.
    fake = FakeListingsService(listings=[_listing("A", price=50.0)], lowest=50.0)
    eng._listings = fake
    assert eng.check_alerts() == 0
    seeded.refresh(w)
    assert w.last_fired_at is None

    # tick2: low 38 <= target, last_fired None -> fire.
    clock.advance(minutes=10)
    fake._listings = [_listing("A", price=38.0)]
    fake._lowest = 38.0
    assert eng.check_alerts() == 1
    seeded.refresh(w)
    assert w.last_fired_at == clock.t

    # tick3: low 38 still below, within cooldown -> 0.
    clock.advance(minutes=10)
    assert eng.check_alerts() == 0
    seeded.refresh(w)
    assert w.last_fired_at is not None  # not reset

    # tick4: low 45 > target -> re-arm (last_fired None), 0.
    clock.advance(minutes=10)
    fake._listings = [_listing("A", price=45.0)]
    fake._lowest = 45.0
    assert eng.check_alerts() == 0
    seeded.refresh(w)
    assert w.last_fired_at is None

    # tick5: low 38 <= target, last_fired None (re-armed) -> fire again.
    clock.advance(minutes=10)
    fake._listings = [_listing("A", price=38.0)]
    fake._lowest = 38.0
    assert eng.check_alerts() == 1

    evs = [e for e in _events(seeded) if e.alert_type == "price_target"]
    assert len(evs) == 2
    for e in evs:
        ctx = json.loads(e.context)
        assert ctx["price"] == 38.0
        assert ctx["target"] == 40.0
        assert ctx["currency"] == "USD"
    assert "price hit target" in evs[0].message


def test_price_target_cooldown(seeded):
    """low stays 38 across two ticks within cooldown -> only 1 fire; advance past
    cooldown -> second fire without re-arm."""
    w = _watch(seeded, alert_type="price_target", target_price=40.0)
    clock = Clock()
    eng = AlertEngine(seeded, clock=clock)
    fake = FakeListingsService(listings=[_listing("A", price=38.0)], lowest=38.0)
    eng._listings = fake

    # tick1: fire.
    assert eng.check_alerts() == 1
    # tick2 within 60 min cooldown -> 0.
    clock.advance(minutes=20)
    assert eng.check_alerts() == 0
    # advance past cooldown -> fire again (no re-arm needed).
    clock.advance(minutes=50)  # total +70 from tick1 fire
    assert eng.check_alerts() == 1
    evs = [e for e in _events(seeded) if e.alert_type == "price_target"]
    assert len(evs) == 2


def test_price_target_never_zero_fabricated(seeded):
    """low None (no priced listings) -> 0 events, no raise, no fabricated 0 price."""
    w = _watch(seeded, alert_type="price_target", target_price=40.0)
    fake = FakeListingsService(listings=[], lowest=None)
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    # Must not raise and must not fabricate a 0-price event.
    n = eng.check_alerts()
    assert n == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert w.last_fired_at is None


# ----------------------------------------------------------- auction_ending


def test_auction_ending_one_event_per_auction(seeded):
    """Two auctions ending in 20 min (window 30) -> 2 events; next tick (clock
    +1 min, same auctions in window) -> 0 (idempotency via existing AlertEvent
    for that listing_id); add a NEW auction in window -> 1 more event for it."""
    end = T0 + timedelta(minutes=20)
    a1 = _listing("auc1", listing_type="auction", auction_end_at=end, price=10.0)
    a2 = _listing("auc2", listing_type="auction", auction_end_at=end, price=12.0)
    fake = FakeListingsService(listings=[a1, a2])
    w = _watch(seeded, alert_type="auction_ending")
    clock = Clock()
    eng = AlertEngine(seeded, listings_service=fake, clock=clock)

    # tick1: both auctions in window -> 2 events.
    assert eng.check_alerts() == 2
    assert len(_events(seeded)) == 2

    # tick2: clock +1 min, same auctions -> idempotent, 0 events.
    clock.advance(minutes=1)
    assert eng.check_alerts() == 0

    # tick3: add a new auction in window -> 1 more event for it.
    a3 = _listing("auc3", listing_type="auction", auction_end_at=T0 + timedelta(minutes=25), price=9.0)
    fake._listings = [a1, a2, a3]
    clock.advance(minutes=1)
    assert eng.check_alerts() == 1

    evs = _events(seeded)
    assert len(evs) == 3
    ids = {json.loads(e.context)["listing_id"] for e in evs}
    assert ids == {"auc1", "auc2", "auc3"}


# --------------------------------------------------------------- drop_time


def test_drop_time_fires_at_lead_and_drop(seeded):
    """drop_at=T+60, lead=60. T -> lead fire; T+30 -> 0; T+60 -> drop fire; T+61 -> 0."""
    drop_at = T0 + timedelta(minutes=60)
    w = _watch(
        seeded,
        alert_type="drop_time",
        card_id=None,
        subject_label="Premium Drop",
        drop_at=drop_at,
        lead_time_min=60,
    )
    clock = Clock()
    eng = AlertEngine(seeded, listings_service=None, clock=clock)

    # T: now >= drop_at-60 -> lead reminder fire.
    assert eng.check_alerts() == 1
    seeded.refresh(w)
    assert w.last_fired_at == T0
    evs = _events(seeded)
    assert evs[-1].message == "Premium Drop: drop in 60 min"

    # T+30: already fired lead, still < drop_at -> 0.
    clock.advance(minutes=30)
    assert eng.check_alerts() == 0

    # T+60: >= drop_at, last_fired < drop_at -> drop fire.
    clock.advance(minutes=30)
    assert eng.check_alerts() == 1
    seeded.refresh(w)
    assert w.last_fired_at == clock.t
    evs = _events(seeded)
    assert evs[-1].message == "Premium Drop: dropping now"

    # T+61: last_fired >= drop_at -> 0.
    clock.advance(minutes=1)
    assert eng.check_alerts() == 0

    assert len([e for e in _events(seeded) if e.alert_type == "drop_time"]) == 2


def test_drop_time_no_fire_before_lead(seeded):
    """drop_at=T+120, lead=60 -> at now=T (< drop_at-60=T+60) -> 0 events."""
    drop_at = T0 + timedelta(minutes=120)
    _watch(
        seeded,
        alert_type="drop_time",
        card_id=None,
        subject_label="Late Drop",
        drop_at=drop_at,
        lead_time_min=60,
    )
    eng = AlertEngine(seeded, listings_service=None, clock=Clock())

    assert eng.check_alerts() == 0
    assert _events(seeded) == []


# ----------------------------------------------------- robustness / safety


def test_provider_empty_no_event_no_raise(seeded):
    """listings_service returns [] for a restock watch (last_seen already [A]) ->
    0 events, no raise, last_seen updated to []."""
    w = _watch(seeded, alert_type="restock", last_seen_listing_ids=json.dumps(["A"]))
    fake = FakeListingsService(listings=[])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    n = eng.check_alerts()
    assert n == 0
    assert _events(seeded) == []
    seeded.refresh(w)
    assert json.loads(w.last_seen_listing_ids) == []


def test_check_alerts_never_raises(seeded):
    """One watch's evaluation raises internally (refresh raises for its card) ->
    engine logs and continues; the OTHER watch in the same tick still fires and is
    counted. No exception propagates."""
    # Second card + set so the good watch has its own card.
    seeded.add(CardSet(id="base2", name="Base 2", series="Base"))
    seeded.add(Card(id="base2-5", set_id="base2", name="Blastoise", number="5"))
    seeded.commit()

    # Bad watch: refresh raises for its card_id.
    bad = _watch(seeded, alert_type="restock", last_seen_listing_ids=json.dumps(["X"]))
    # Good watch: new_listing on a different card, fires 1.
    good = _watch(
        seeded,
        card_id="base2-5",
        alert_type="new_listing",
        last_seen_listing_ids=json.dumps(["A"]),
    )
    fake = FakeListingsService(
        listings=[_listing("A"), _listing("B")], raise_on="base1-4"
    )
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    # Must not raise.
    n = eng.check_alerts()
    assert n == 1  # only the good watch fired
    evs = _events(seeded)
    assert len(evs) == 1
    assert evs[0].watch_id == good.id


def test_inactive_watches_skipped(seeded):
    """A watch with active=False -> not evaluated (0 events even if it would fire)."""
    _watch(
        seeded,
        alert_type="new_listing",
        last_seen_listing_ids=json.dumps(["A"]),
        active=False,
    )
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    assert eng.check_alerts() == 0
    assert _events(seeded) == []


def test_idempotent_across_ticks_no_change(seeded):
    """Run check_alerts twice with identical state -> second returns 0 (no
    duplicate events; last_seen updated means no new_listing on the second tick)."""
    w = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    assert eng.check_alerts() == 1
    # Second tick: last_seen is now [A,B], curr still {A,B} -> no new ids -> 0.
    assert eng.check_alerts() == 0
    assert len(_events(seeded)) == 1


def test_notifier_dispatched_and_failure_does_not_break(seeded):
    """A fake notifier whose dispatch appends to a list (and one variant whose
    dispatch raises) -> event rows still created (delivered_inapp True), count
    correct, no raise from the raising notifier, other watches still processed."""
    # Two new_listing watches, both fire. The notifier raises for the second.
    w1 = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    w2 = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    notifier = FakeNotifier(raise_on=w2.id)
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, notifier=notifier, clock=Clock())

    n = eng.check_alerts()
    assert n == 2  # both watches fired
    evs = _events(seeded)
    assert len(evs) == 2
    assert all(e.delivered_inapp for e in evs)
    # The notifier dispatched for both (append happens before the conditional raise).
    assert len(notifier.events) == 2
    # No exception propagated (we reached these assertions).


def test_flush_failure_does_not_poison_tick(seeded):
    """A flush IntegrityError during the FIRST watch's _fire must not poison the
    session for the rest of the tick. The SAVEPOINT rolls back the failed
    insert, the second watch still fires, and check_alerts returns without
    raising (the final commit also does not escape).

    Path taken: monkeypatch `session.flush` to raise `sqlalchemy.exc.
    IntegrityError` on the first flush that runs while an AlertEvent is
    pending in `session.new` — i.e. the explicit flush inside `_fire` for the
    first watch (the only place an AlertEvent is added then flushed). This
    simulates an FK violation on AlertEvent insert (the realistic
    flush-poisoning trigger, since AlertEvent has no unique constraint) and
    directly exercises the PendingRollbackError cascade the SAVEPOINT
    isolation guards; a bare refresh-raises test would not, because refresh
    happens before any flush.
    """
    from sqlalchemy.exc import IntegrityError

    w1 = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    w2 = _watch(seeded, alert_type="new_listing", last_seen_listing_ids=json.dumps(["A"]))
    fake = FakeListingsService(listings=[_listing("A"), _listing("B")])
    eng = AlertEngine(seeded, listings_service=fake, clock=Clock())

    real_flush = seeded.flush
    poisoned = {"first": True}

    def flaky_flush(*a, **kw):
        # Only poison the flush that has an AlertEvent pending (inside _fire).
        # Autoflushes from the initial Watch query run with session.new empty
        # and must be left alone so the tick can start.
        has_alert = any(isinstance(o, AlertEvent) for o in seeded.new)
        if has_alert and poisoned["first"]:
            poisoned["first"] = False
            raise IntegrityError(
                "INSERT INTO alert_events ... FOREIGN KEY constraint failed",
                {},
                Exception("fk violation"),
            )
        return real_flush(*a, **kw)

    seeded.flush = flaky_flush
    try:
        # Must not raise — not on the failed watch, not on the final commit.
        n = eng.check_alerts()
    finally:
        seeded.flush = real_flush

    assert isinstance(n, int)
    evs = _events(seeded)
    # w1's event was rolled back by the savepoint; w2's event persisted.
    assert len(evs) == 1
    assert evs[0].watch_id == w2.id
    assert evs[0].alert_type == "new_listing"