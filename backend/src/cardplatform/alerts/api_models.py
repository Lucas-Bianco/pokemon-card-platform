"""Pydantic wire models for the Phase 3c alert/watchlist/listings/push API.

Mirrors the rest of `api.py`: Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`
so the ORM-mapped `Watch` / `ListingSnapshot` / `AlertEvent` rows serialise directly.
Every nullable column surfaces as None rather than a fabricated default, matching
the project's honest-empty-state convention (a missing figure is never a zero).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WatchOut(BaseModel):
    """One watch subscription. `active` defaults True at the model level; the
    PATCH endpoint flips it. `last_fired_at` / `last_seen_listing_ids` are engine
    state — only `last_fired_at` surfaces here (the listing-id baseline is internal
    to the diff engine and not useful to the frontend)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    card_id: str | None
    subject_label: str | None
    variant: str | None
    alert_type: str
    target_price: float | None
    drop_at: datetime | None
    lead_time_min: int | None
    auction_window_min: int | None
    active: bool
    last_fired_at: datetime | None
    created_at: datetime


class WatchCreate(BaseModel):
    """Inbound watch. `card_id` is optional so a watch can target a non-card
    subject via `subject_label`. Validation (alert_type membership, required
    fields per alert_type) lives in the endpoint, not here — Pydantic cannot
    express 'target_price required iff alert_type == price_target' cleanly."""

    card_id: str | None = None
    subject_label: str | None = None
    variant: str | None = None
    alert_type: str
    target_price: float | None = None
    drop_at: datetime | None = None
    lead_time_min: int | None = None
    auction_window_min: int | None = None


class WatchPatch(BaseModel):
    """Partial update to a watch. Every field is optional; a field that is absent
    (None) is left untouched, mirroring `CollectionItemUpdate`."""

    active: bool | None = None
    target_price: float | None = None
    drop_at: datetime | None = None
    lead_time_min: int | None = None
    auction_window_min: int | None = None


class ListingOut(BaseModel):
    """One marketplace listing from the newest snapshot. `source` is required
    (no fabricated default); every nullable column surfaces as None when the
    source omits it."""

    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    title: str | None
    price: float | None
    currency: str | None
    listing_type: str | None
    auction_end_at: datetime | None
    url: str | None
    condition: str | None
    source: str
    fetched_at: datetime


class AlertEventOut(BaseModel):
    """One fired alert for the in-app notification feed. `read_at` is None until
    the user opens it; the feed's unread badge is computed from it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    watch_id: int | None
    card_id: str | None
    alert_type: str
    message: str
    context: str | None
    delivered_push: bool
    delivered_email: bool
    read_at: datetime | None
    created_at: datetime


class PushSubscribeIn(BaseModel):
    """A Web Push subscription endpoint + its ECDH key material. The browser
    generates p256dh/auth on subscribe; they rotate, so the upsert updates them
    when the same endpoint re-subscribes."""

    endpoint: str
    p256dh: str
    auth: str