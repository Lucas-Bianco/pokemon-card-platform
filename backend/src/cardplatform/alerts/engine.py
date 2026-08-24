"""Alert evaluation engine for Phase 3c.

`AlertEngine.check_alerts()` runs one tick: every active `Watch` is evaluated
against the latest listing state (via `ListingsService`) and/or the clock, and
fired alerts are written as immutable `AlertEvent` rows. The engine NEVER raises
out of `check_alerts()` — one bad watch (or a failing notifier, or a transient
commit failure) is logged and skipped so a single corrupt row or DB blip cannot
silence the rest of the tick or crash the poll loop.

CRITICAL design decision — baselines live on the WATCH, not the snapshot table:

With immutable `ListingSnapshot` rows and no fetch-record table, an *empty*
fetch inserts no rows, so it is invisible to `ListingsService.previous_listing_ids`
(the prior snapshot). Restock/new_listing idempotency therefore MUST use
`Watch.last_seen_listing_ids` (a JSON-encoded list of the listing_ids this watch
last observed) as the authoritative per-watch baseline. We do NOT use
`previous_listing_ids` as the baseline for restock/new_listing — it cannot
observe the empty -> stocked transition because empty fetches leave no trace.
`latest_listings` is still the source of the CURRENT listing set.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from cardplatform.db.models import AlertEvent, Card, Watch

log = logging.getLogger(__name__)

# Alert types that read the live listing set each tick. Their listings are
# refreshed once per watch in check_alerts BEFORE the per-watch savepoint —
# NOT from inside the eval. ListingsService.refresh_listings commits the
# outer transaction, and a commit emitted inside the begin_nested()
# savepoint closes that savepoint; its context manager then raises on exit,
# the never-raise handler swallows it, and the watch is silently skipped.
# That bug suppressed every listing-based alert whenever a real
# ListingsService (whose refresh commits, unlike the test FakeListingsService)
# was wired through check_alerts — i.e. the production poll loop and the
# on-demand /alerts/check route. Refreshing before the savepoint keeps the
# commit's transaction boundary intact; the savepoint then only guards the
# eval's flush, which is all it was ever meant to do.
_LISTING_ALERT_TYPES = frozenset(
    {"restock", "new_listing", "price_target", "auction_ending"}
)


class AlertEngine:
    """Evaluates active watches each tick and writes AlertEvent rows.

    All collaborators are optional/injectable so tests can drive deterministic
    ticks without touching the network or the wall clock. The engine commits
    exactly once per tick (at the end) and never raises.
    """

    def __init__(
        self,
        session: Session,
        listings_service=None,
        notifier=None,
        settings=None,
        clock: Optional[Callable[[], datetime]] = None,
        deal_engine=None,
    ) -> None:
        self.session = session
        self._listings = listings_service
        self._notifier = notifier
        self._settings = settings
        self._deal_engine = deal_engine
        # Never call datetime.now() directly — always self._now() so tests
        # control time via the injected clock.
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    # ----------------------------------------------------------- helpers

    def _now(self) -> datetime:
        return self._clock()

    def _cooldown_min(self) -> int:
        """alert_cooldown_min from settings, default 60. T4 owns config; we
        only read, never add."""
        if self._settings is None:
            return 60
        return getattr(self._settings, "alert_cooldown_min", 60)

    def _card_name(self, card_id) -> Optional[str]:
        """Card.name lookup; falls back to None on miss/failure (never raises)."""
        if card_id is None:
            return None
        try:
            card = self.session.query(Card).filter(Card.id == card_id).first()
            if card is not None:
                return card.name
        except Exception:
            log.warning("card lookup failed for card_id=%s", card_id, exc_info=True)
        return None

    def _display(self, w: Watch, subject_first: bool = False) -> str:
        """Human-readable subject for messages. Listing-based alerts prefer the
        card name; drop_time prefers the subject_label (per contract). Falls
        back gracefully so a missing card never raises."""
        card_name = self._card_name(w.card_id)
        if subject_first:
            return w.subject_label or card_name or str(w.card_id)
        return card_name or w.subject_label or str(w.card_id)

    def _refresh_for(self, w: Watch) -> None:
        """Refresh listings for the watch's card+variant, ONCE, before the
        per-watch savepoint. Only the listing-based alert types need a fresh
        fetch; deal/drop_time do not read this service. Never raises — a
        refresh failure (no key, network, transport) is logged and the watch
        is skipped by the caller, preserving the never-raise tick contract."""
        if self._listings is None or w.card_id is None:
            return
        if w.alert_type not in _LISTING_ALERT_TYPES:
            return
        try:
            # Ignore the returned count; refresh just populates snapshots.
            self._listings.refresh_listings(w.card_id, w.variant or "")
        except Exception:
            log.warning("refresh failed for watch %s", w.id, exc_info=True)
            raise

    def _current_listings(self, w: Watch):
        """Return latest listings for the watch's card+variant, or None if
        there is no listings_service (caller skips silently). Read-only — the
        refresh happens once per watch in check_alerts, OUTSIDE the savepoint
        (see _LISTING_ALERT_TYPES)."""
        if self._listings is None:
            return None
        return self._listings.latest_listings(w.card_id, w.variant or "")

    def _fire(self, w: Watch, message: str, context: str) -> None:
        """Insert one immutable AlertEvent row and dispatch the notifier if any.

        `session.flush()` makes the row queryable (and gives it an id) before
        the tick's commit, so intra-tick idempotency checks and the notifier
        both see it. A notifier failure is logged and swallowed so a broken
        delivery channel never blocks the in-app event row.
        """
        event = AlertEvent(
            watch_id=w.id,
            card_id=w.card_id,
            alert_type=w.alert_type,
            message=message,
            context=context,
            delivered_inapp=True,
            delivered_push=False,
            delivered_email=False,
            read_at=None,
        )
        self.session.add(event)
        self.session.flush()
        if self._notifier is not None:
            try:
                self._notifier.dispatch(event)
            except Exception:
                log.warning("notifier dispatch failed", exc_info=True)

    # ----------------------------------------------------------- main loop

    def check_alerts(self) -> int:
        """Evaluate every active Watch, write AlertEvent rows, commit once.
        Returns the count of events created this tick. Never raises — not on a
        bad watch, a failing notifier, nor a transient final-commit failure."""
        count = 0
        watches = (
            self.session.query(Watch)
            .filter(Watch.active == True)  # noqa: E712  -- SQLAlchemy filter
            .order_by(Watch.id)
            .all()
        )
        for w in watches:
            try:
                # Refresh FIRST, outside the savepoint: refresh_listings commits
                # the outer transaction, and a commit inside begin_nested()
                # would close the savepoint and silently suppress this watch
                # (see _LISTING_ALERT_TYPES). A refresh failure raises here and
                # is caught by the same never-raise guard below — the watch is
                # skipped, the rest of the tick proceeds.
                self._refresh_for(w)
                # A SAVEPOINT isolates this watch's flush from the outer
                # transaction. If _eval (or _fire's flush) raises, the savepoint
                # ROLLs back to here and re-raises; the outer except swallows it
                # and the session stays usable for the next watch. Without this,
                # a flush IntegrityError would poison the session with a pending
                # rollback -> every later watch's first query raises
                # PendingRollbackError and the final commit would ESCAPE,
                # violating the never-raise contract. Prior watches' successful
                # rows stay in the outer (uncommitted) transaction and are
                # committed by the final commit below (or by the next watch's
                # refresh, which commits the outer transaction — also fine).
                with self.session.begin_nested():
                    count += self._eval(w)
            except Exception:
                # One bad watch must not silence the rest of the tick.
                # begin_nested()'s context manager already rolled back to the
                # savepoint on the exception; the session remains usable.
                log.warning("watch %s evaluation failed", w.id, exc_info=True)
                continue
        # Truly never-raise: a transient commit failure (hard DB error) is logged
        # and rolled back rather than crashing the T5 poll loop. The count of
        # events created this tick is returned even if the commit failed (those
        # rows are lost on rollback, but the caller still gets an honest int and
        # the loop survives).
        try:
            self.session.commit()
        except Exception:
            log.warning("check_alerts final commit failed; rolling back", exc_info=True)
            try:
                self.session.rollback()
            except Exception:
                log.warning("rollback after failed commit also failed", exc_info=True)
        return count

    def _eval(self, w: Watch) -> int:
        now = self._now()
        atype = w.alert_type
        if atype == "restock":
            return self._eval_restock(w, now)
        if atype == "new_listing":
            return self._eval_new_listing(w, now)
        if atype == "price_target":
            return self._eval_price_target(w, now)
        if atype == "auction_ending":
            return self._eval_auction_ending(w, now)
        if atype == "drop_time":
            return self._eval_drop_time(w, now)
        if atype == "deal":
            return self._eval_deal(w, now)
        log.warning("unknown alert_type %r for watch %s", atype, w.id)
        return 0

    # ----------------------------------------------------------- restock

    def _eval_restock(self, w: Watch, now: datetime) -> int:
        if w.card_id is None:
            log.debug("restock watch %s has no card_id; skipping", w.id)
            return 0
        curr = self._current_listings(w)
        if curr is None:
            return 0
        curr_ids = {s.listing_id for s in curr}
        prev_ids = (
            set(json.loads(w.last_seen_listing_ids)) if w.last_seen_listing_ids else None
        )
        # First poll: establish baseline, never fire.
        if prev_ids is None:
            w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
            return 0
        fired = 0
        # Restock fires iff previously observed EMPTY and now stocked.
        if not prev_ids and bool(curr_ids):
            msg = f"{self._display(w)}: back in stock"
            ctx = json.dumps({"listing_ids": sorted(curr_ids), "source": "ebay"})
            self._fire(w, msg, ctx)
            fired += 1
        # Always advance the baseline (even when curr is empty) so the
        # empty -> stocked transition is observable on a later tick.
        w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
        return fired

    # ------------------------------------------------------- new_listing

    def _eval_new_listing(self, w: Watch, now: datetime) -> int:
        if w.card_id is None:
            log.debug("new_listing watch %s has no card_id; skipping", w.id)
            return 0
        curr = self._current_listings(w)
        if curr is None:
            return 0
        curr_ids = {s.listing_id for s in curr}
        prev_ids = (
            set(json.loads(w.last_seen_listing_ids)) if w.last_seen_listing_ids else None
        )
        if prev_ids is None:
            w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
            return 0
        new_ids = curr_ids - prev_ids
        fired = 0
        if new_ids:
            msg = f"{self._display(w)}: {len(new_ids)} new listing(s)"
            ctx = json.dumps(
                {
                    "new_listing_ids": sorted(new_ids),
                    "count": len(new_ids),
                    "source": "ebay",
                }
            )
            self._fire(w, msg, ctx)
            fired += 1
        w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
        return fired

    # --------------------------------------------------------------- deal

    def _eval_deal(self, w: Watch, now: datetime) -> int:
        """Fire when a NEW active listing clears the rip/flip deal thresholds.

        Mirrors _eval_new_listing's baseline-dedupe: the first poll establishes
        the baseline (never fires); subsequent polls fire only for listing ids
        that are deals AND not yet in the baseline. The baseline always advances
        (even to empty) so a listing that stops being a deal cannot re-fire.
        Reuses the global deal thresholds via the read-only DealEngine — no
        per-watch thresholds, no snapshot writes. A missing deal_engine is a
        silent no-op, never a crash.
        """
        if w.card_id is None:
            log.debug("deal watch %s has no card_id; skipping", w.id)
            return 0
        if self._deal_engine is None:
            log.debug("deal watch %s has no deal_engine; skipping", w.id)
            return 0
        variant = w.variant or ""
        try:
            assessments = self._deal_engine.assess(w.card_id, variant)
        except Exception:
            # DealEngine.assess never raises per Phase 05, but defend the
            # never-raise contract: a deal evaluation failure is a skip.
            log.warning("deal assess failed for watch %s", w.id, exc_info=True)
            return 0
        deal_map = {a.listing_id: a for a in assessments if a.is_rip or a.is_flip}
        curr_ids = set(deal_map)
        prev_ids = (
            set(json.loads(w.last_seen_listing_ids)) if w.last_seen_listing_ids else None
        )
        # First poll: establish baseline, never fire.
        if prev_ids is None:
            w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
            return 0
        new_ids = curr_ids - prev_ids
        fired = 0
        for lid in sorted(new_ids):
            a = deal_map[lid]
            self._fire(w, self._deal_message(w, a), self._deal_context(a))
            fired += 1
        # Always advance the baseline so removed deals don't re-fire.
        w.last_seen_listing_ids = json.dumps(sorted(curr_ids))
        return fired

    def _deal_message(self, w: Watch, a) -> str:
        name = self._display(w)
        price = a.listing_price
        price_str = f"${price:.2f}" if price is not None else "—"
        rip = a.rip_edge
        flip = a.flip_edge_to_10
        rip_str = f"${rip:.2f}" if rip is not None else None
        flip_str = f"${flip:.2f}" if flip is not None else None
        # Lead with the larger of the two edges.
        if a.is_rip and (not a.is_flip or (rip is not None and flip is not None and rip >= flip)):
            return (f"Deal on {name} — listing {price_str} vs market, RIP edge {rip_str}. "
                    f"Verify before buying.")
        if a.is_flip and flip_str is not None:
            return (f"Deal on {name} — listing {price_str}, PSA-10 flip spread {flip_str} "
                    f"after grading. Verify before buying.")
        return f"Deal on {name} — listing {price_str}. Verify before buying."

    def _deal_context(self, a) -> str:
        def _pp(p):
            if p is None:
                return None
            return {"price": p.price, "source": p.source, "source_updated_at": p.source_updated_at}
        return json.dumps({
            "listing_id": a.listing_id,
            "url": a.url,
            "listing_price": a.listing_price,
            "currency": a.currency,
            "condition": a.condition,
            "rip_edge": a.rip_edge,
            "flip_edge_to_10": a.flip_edge_to_10,
            "is_rip": a.is_rip,
            "is_flip": a.is_flip,
            "deal_score": a.deal_score,
            "raw_market": _pp(getattr(a, "raw_market", None)),
        })

    # ------------------------------------------------------- price_target

    def _eval_price_target(self, w: Watch, now: datetime) -> int:
        if w.target_price is None:
            log.warning("price_target watch %s has no target_price; skipping", w.id)
            return 0
        if w.card_id is None or self._listings is None:
            return 0
        variant = w.variant or ""
        # Read-only: the refresh happened once in check_alerts before the
        # savepoint (see _LISTING_ALERT_TYPES). Committing here would close the
        # savepoint and silently suppress the alert.
        low = self._listings.lowest_price(w.card_id, variant)
        if low is None:
            # No priced listings. Do NOT reset last_fired_at here — keep state.
            return 0
        cooldown = self._cooldown_min()
        # Price rose above target -> re-arm (next crossing fires fresh).
        if low > w.target_price:
            w.last_fired_at = None
            return 0
        # low <= target: fire iff not in cooldown.
        if w.last_fired_at is None or (now - w.last_fired_at) >= timedelta(minutes=cooldown):
            # Currency comes from the lowest-priced current listing.
            currency = None
            for s in self._listings.latest_listings(w.card_id, variant):
                if s.price == low:
                    currency = s.currency
                    break
            msg = (
                f"{self._display(w)}: price hit target "
                f"(${low:.2f} ≤ ${w.target_price:.2f})"
            )
            ctx = json.dumps(
                {"price": low, "target": w.target_price, "currency": currency}
            )
            self._fire(w, msg, ctx)
            w.last_fired_at = now
            return 1
        return 0

    # ----------------------------------------------------- auction_ending

    def _eval_auction_ending(self, w: Watch, now: datetime) -> int:
        if w.card_id is None:
            log.debug("auction_ending watch %s has no card_id; skipping", w.id)
            return 0
        curr = self._current_listings(w)
        if curr is None:
            return 0
        window = w.auction_window_min or 30
        fired = 0
        horizon = now + timedelta(minutes=window)
        for s in curr:
            if s.listing_type != "auction":
                continue
            if s.auction_end_at is None:
                continue
            if not (now <= s.auction_end_at <= horizon):
                continue
            # Idempotency: one AlertEvent per (watch, listing_id). The schema's
            # `context` is a JSON-encoded String, so a LIKE match on the
            # serialized listing_id is the pragmatic dedupe — this mirrors the
            # codebase's func.lower().like text-search convention adapted to a
            # JSON string. A structured column would be cleaner but is out of
            # scope for T3's schema. listing_ids are numeric/opaque (no LIKE
            # wildcards or quotes); a mixed/wildcard id source would need a
            # dedicated dedupe column.
            already = (
                self.session.query(AlertEvent)
                .filter(
                    AlertEvent.watch_id == w.id,
                    AlertEvent.alert_type == "auction_ending",
                    AlertEvent.context.like(f'%"listing_id": "{s.listing_id}"%'),
                )
                .first()
            )
            if already is not None:
                continue
            mins = int((s.auction_end_at - now).total_seconds() // 60)
            msg = f"{self._display(w)}: auction ends in {mins} min"
            ctx = json.dumps(
                {
                    "listing_id": s.listing_id,
                    "auction_end_at": s.auction_end_at.isoformat(),
                    "url": s.url,
                }
            )
            self._fire(w, msg, ctx)
            fired += 1
        # Do NOT update last_seen_listing_ids for auction_ending.
        return fired

    # --------------------------------------------------------- drop_time

    def _eval_drop_time(self, w: Watch, now: datetime) -> int:
        if w.drop_at is None:
            log.warning("drop_time watch %s has no drop_at; skipping", w.id)
            return 0
        lead = w.lead_time_min or 0
        fire_window_start = w.drop_at - timedelta(minutes=lead)
        # Two fires: lead-time reminder, then the drop itself. First fire when
        # last_fired_at is None and now is within the lead window. Second fire
        # when last_fired_at is the lead-time fire (strictly < drop_at) and now
        # has reached drop_at. After the drop fire last_fired_at >= drop_at so
        # it cannot fire again. (The contract's formula used `< drop_at - lead`
        # in the second clause, which would block the drop fire entirely; the
        # prose and tests require `< drop_at`, which is what's implemented.)
        should_fire = now >= fire_window_start and (
            w.last_fired_at is None
            or (w.last_fired_at < w.drop_at and now >= w.drop_at)
        )
        if not should_fire:
            return 0
        if now < w.drop_at:
            mins = int((w.drop_at - now).total_seconds() // 60)
            msg = f"{self._display(w, subject_first=True)}: drop in {mins} min"
        else:
            msg = f"{self._display(w, subject_first=True)}: dropping now"
        ctx = json.dumps({"drop_at": w.drop_at.isoformat(), "lead_time_min": lead})
        self._fire(w, msg, ctx)
        w.last_fired_at = now
        return 1