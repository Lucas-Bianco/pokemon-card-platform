"""SQLAlchemy models for catalog, prices, and collection."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """SQLite has no tz-aware type. Normalize to UTC on write, re-attach UTC on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; pass an aware datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class CardSet(Base):
    """A Pokemon TCG set. Named CardSet because `Set` shadows typing.Set."""

    __tablename__ = "card_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    series: Mapped[str | None] = mapped_column(String, default=None)
    printed_total: Mapped[int | None] = mapped_column(Integer, default=None)
    total: Mapped[int | None] = mapped_column(Integer, default=None)
    ptcgo_code: Mapped[str | None] = mapped_column(String, default=None)
    release_date: Mapped[str | None] = mapped_column(String, index=True, default=None)
    image_symbol: Mapped[str | None] = mapped_column(String, default=None)
    image_logo: Mapped[str | None] = mapped_column(String, default=None)

    cards: Mapped[list[Card]] = relationship(back_populates="card_set")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    set_id: Mapped[str] = mapped_column(ForeignKey("card_sets.id"), index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    number: Mapped[str] = mapped_column(String, index=True)
    rarity: Mapped[str | None] = mapped_column(String, default=None)
    supertype: Mapped[str | None] = mapped_column(String, default=None)
    subtypes: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    artist: Mapped[str | None] = mapped_column(String, default=None)
    national_pokedex_numbers: Mapped[list[int] | None] = mapped_column(JSON, default=None)
    image_small: Mapped[str | None] = mapped_column(String, default=None)
    image_large: Mapped[str | None] = mapped_column(String, default=None)

    card_set: Mapped[CardSet] = relationship(back_populates="cards")


class PriceSnapshot(Base):
    """Immutable point-in-time price observation.

    Rows are never updated. History accrues so Phase 2 can chart P/L and Phase 5 can
    detect underpriced listings against a baseline.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("card_id", "source", "variant", "source_updated_at", name="uq_snapshot"),
        Index("ix_snapshot_lookup", "card_id", "variant", "source", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    source: Mapped[str] = mapped_column(String, index=True)  # "tcgplayer" | "cardmarket"
    variant: Mapped[str] = mapped_column(String, index=True)  # "holofoil", "reverseHolofoil", ...
    low: Mapped[float | None] = mapped_column(Float, default=None)
    mid: Mapped[float | None] = mapped_column(Float, default=None)
    high: Mapped[float | None] = mapped_column(Float, default=None)
    market: Mapped[float | None] = mapped_column(Float, default=None)
    # Non-nullable with an empty-string sentinel: SQL treats NULLs as distinct in
    # unique constraints, so a NULL here would defeat uq_snapshot's dedupe whenever a
    # source omits its timestamp. "" collides correctly; NULL would not.
    source_updated_at: Mapped[str] = mapped_column(String, default="", server_default="")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    variant: Mapped[str] = mapped_column(String, default="normal")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    condition: Mapped[str | None] = mapped_column(String, default=None)
    acquired_price: Mapped[float | None] = mapped_column(Float, default=None)
    acquired_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    card: Mapped[Card] = relationship()


class ScanLog(Base):
    """One recognition attempt, kept for evaluation and future fine-tuning.

    This is the project's only source of labelled real-world data: every accuracy
    figure so far came from degraded reference images, and improving on that depends
    on users correcting wrong answers — which is only useful if the image that
    produced the answer was kept.
    """

    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_path: Mapped[str] = mapped_column(String)
    predicted_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("cards.id"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(String, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    visual_margin: Mapped[float | None] = mapped_column(Float, default=None)
    collector_number_read: Mapped[str | None] = mapped_column(String, default=None)
    # Set when the user says the prediction was wrong. NULL means "not reviewed",
    # which is deliberately different from "reviewed and correct" — see `confirmed`.
    corrected_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("cards.id"), index=True, default=None
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    # Phase 3b: the rectified crop (a deskewed, border-cropped image produced by
    # T2 on recognize) and the variant the user picked for it. Nullable so the
    # 101 existing rows get NULL; added via run_migrations, not create_all.
    rectified_path: Mapped[str | None] = mapped_column(String, default=None)
    variant: Mapped[str | None] = mapped_column(String, default=None)
    # Phase 4: groups the N rows of one bulk-cataloger photo. NULL for single-card
    # scans (treated as a singleton batch). batch_index is the slot position within
    # the batch. Both nullable, added via run_migrations, not create_all — the 105
    # existing rows stay NULL.
    batch_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    batch_index: Mapped[int | None] = mapped_column(Integer, default=None)


class GradingLabel(Base):
    """A third-party grading verdict attached to one scan (one label per scan).

    Phase 3b stores the label a user received back from PSA/CGC/BGS alongside
    the scan it grades; later tasks use it to look up graded prices and compute
    grading upside vs. raw market price.
    """

    __tablename__ = "grading_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scan_logs.id"), unique=True
    )  # one label per scan
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    # Nullable: a scan that never picked a variant is honestly None, not a
    # fabricated "normal". T1 originally created this NOT NULL; T3 relaxed it
    # (see _ensure_grading_labels_variant_nullable in migrations) so a label can
    # carry the same absence the scan does, without inventing a variant.
    variant: Mapped[str | None] = mapped_column(String, default=None)
    # PSA grades are whole numbers; BGS/CGC may use .5 increments (e.g. 9.5).
    # Float covers both; stored this way up front to avoid a later migration.
    grade: Mapped[float] = mapped_column(Float)
    grader: Mapped[str] = mapped_column(String)  # "PSA" | "CGC" | "BGS"
    cert_number: Mapped[str | None] = mapped_column(String, default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class GradedPriceSnapshot(Base):
    """Immutable point-in-time graded-price observation, mirroring PriceSnapshot.

    Rows are never updated; history accrues so T5 can chart graded-vs-raw spread
    over time. Dedupes on (card_id, grader, grade, variant, source_updated_at)
    using the same empty-string sentinel trick as PriceSnapshot: NULLs are
    distinct under a unique constraint, so a missing source timestamp is stored
    as "" to collide correctly instead of silently duplicating.
    """

    __tablename__ = "graded_price_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "grader", "grade", "variant", "source_updated_at",
            name="uq_graded_snapshot",
        ),
        Index(
            "ix_graded_snapshot_lookup", "card_id", "variant", "grader", "grade", "fetched_at"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    grader: Mapped[str] = mapped_column(String, index=True)  # "PSA" | "CGC" | "BGS"
    # PSA grades are whole numbers; BGS/CGC may use .5 increments (e.g. 9.5).
    # Float covers both; stored this way up front to avoid a later migration.
    grade: Mapped[float] = mapped_column(Float, index=True)
    variant: Mapped[str] = mapped_column(String, index=True)
    low: Mapped[float | None] = mapped_column(Float, default=None)
    mid: Mapped[float | None] = mapped_column(Float, default=None)
    high: Mapped[float | None] = mapped_column(Float, default=None)
    market: Mapped[float | None] = mapped_column(Float, default=None)
    source: Mapped[str] = mapped_column(String, index=True)  # e.g. "pkmnprices"
    # See PriceSnapshot: '' collides under the unique constraint; NULL would not.
    source_updated_at: Mapped[str] = mapped_column(String, default="", server_default="")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Watch(Base):
    """A user watch: one row per alert subscription (price drop, auction, etc.).

    Phase 3c's source of intent. `card_id` is nullable so a watch can target a
    non-card subject (a set, a grade tier) via `subject_label`; `variant` is
    nullable because not every alert type is variant-scoped. Dedupes on the
    five-tuple (card_id, variant, alert_type, target_price, drop_at) so the
    same alert re-armed with the same params is one row, not many.
    """

    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "variant", "alert_type", "target_price", "drop_at",
            name="uq_watch",
        ),
        Index("ix_watch_card", "card_id", "variant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id"), index=True, default=None)
    subject_label: Mapped[str | None] = mapped_column(String, default=None)
    variant: Mapped[str | None] = mapped_column(String, default=None)
    alert_type: Mapped[str] = mapped_column(String, index=True)
    target_price: Mapped[float | None] = mapped_column(Float, default=None)
    drop_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    lead_time_min: Mapped[int | None] = mapped_column(Integer, default=None)
    auction_window_min: Mapped[int | None] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_listing_ids: Mapped[str | None] = mapped_column(String, default=None)
    last_fired_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ListingSnapshot(Base):
    """Immutable point-in-time snapshot of a single marketplace listing.

    Rows are never updated; each fetch appends a new row so Phase 3c can diff
    consecutive snapshots to detect price drops and new listings. Dedupes on
    (card_id, variant, source, listing_id, source_updated_at) using the same
    empty-string sentinel trick as PriceSnapshot: a missing source timestamp
    is stored as "" to collide correctly under the unique constraint.
    """

    __tablename__ = "listing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "variant", "source", "listing_id", "source_updated_at",
            name="uq_listing",
        ),
        Index("ix_listing_lookup", "card_id", "variant", "source", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    variant: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    listing_id: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, default=None)
    price: Mapped[float | None] = mapped_column(Float, default=None)
    currency: Mapped[str | None] = mapped_column(String, default=None)
    listing_type: Mapped[str | None] = mapped_column(String, default=None)
    auction_end_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    url: Mapped[str | None] = mapped_column(String, default=None)
    condition: Mapped[str | None] = mapped_column(String, default=None)
    quantity: Mapped[int | None] = mapped_column(Integer, default=None)
    source_updated_at: Mapped[str] = mapped_column(String, default="", server_default="")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class AlertEvent(Base):
    """One fired alert, retained for the in-app notification feed and audit.

    `read_at` is NULL until the user opens it, which is how the unread badge
    is computed. The (read_at, created_at) index serves the unread-first
    ordering the feed uses. FKs to watchlist and cards are nullable: an event
    may outlive its watch (deleted watches keep history) and a subject_label
    watch has no card_id.
    """

    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_unread", "read_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist.id"), index=True, default=None)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id"), index=True, default=None)
    alert_type: Mapped[str] = mapped_column(String, index=True)
    message: Mapped[str] = mapped_column(String)
    context: Mapped[str | None] = mapped_column(String, default=None)
    delivered_inapp: Mapped[bool] = mapped_column(Boolean, default=True)
    delivered_push: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_email: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class PushSubscription(Base):
    """A Web Push subscription endpoint for delivering alerts to a device.

    One endpoint per device; duplicates collide via the `unique` constraint on
    `endpoint`. The p256dh/auth keys are the ECDH key material the browser
    generates on subscribe and are required to encrypt each push payload.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SealedPurchase(Base):
    """A reseller's logged sealed-product buy. User-editable (distinct from recognition
    snapshots — resellers correct mistakes). The immutable core of a ledger entry."""

    __tablename__ = "sealed_purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String, index=True)
    product_type: Mapped[str | None] = mapped_column(String, default=None)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    cost_per_unit: Mapped[float] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String, default=None)
    listing_url: Mapped[str | None] = mapped_column(String, default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    bought_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SealedValuation(Base):
    """Append-only market snapshot for a purchase — the sealed surface's price-snapshot
    store (mirrors PriceSnapshot immutability: insert, never update). Latest per purchase
    = max(id). Sourced via the eBay sold-comps provider + median; never fabricated."""

    __tablename__ = "sealed_valuations"
    __table_args__ = (Index("ix_valuation_lookup", "purchase_id", "fetched_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("sealed_purchases.id"), index=True)
    value_per_unit: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String, default="ebay_sold_median")
    comp_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SealedProduct(Base):
    """A sealed Pokémon product in the reference catalog (Phase A, roadmap row 09).

    Sealed products (booster packs, booster boxes, ETBs, collection boxes, tins,
    premium bundles — everything that contains card packs) are NOT cards: no
    card_id/variant, no price snapshots here. This is static reference data — the
    keystone for scan-to-log (B), MSRP-vs-market (C), price-lookup (D), shopping (E).

    Honesty: `msrp` is nullable. Many sealed products have NO official US MSRP
    (booster boxes aren't sold at a fixed retail price; premiums vary) — those rows
    are NULL and the UI shows "no MSRP", never a fabricated $0. `print_status` is a
    best-effort tag (in_print/out_of_print/unknown), never a guarantee (products
    re-enter print; unknown is honest, not a guess). `source` records row provenance
    ("manual" for the curated starter seed; a community sync would set its own).

    String slug PK (idempotent seeding by natural key, mirrors CardSet). Auto-
    provisioned by `Base.metadata.create_all()` — no migration needed for a new
    table. The starter seed lives in `sealed/seed_data.py` (in-repo, version-
    controlled — NOT under data/, which is user data we never touch).
    """

    __tablename__ = "sealed_products"
    __table_args__ = (Index("ix_sealed_product_browse", "product_type", "print_status"),)

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    era: Mapped[str | None] = mapped_column(String, index=True, default=None)
    product_type: Mapped[str] = mapped_column(String, index=True)
    msrp: Mapped[float | None] = mapped_column(Float, default=None)
    msrp_currency: Mapped[str] = mapped_column(String, default="USD")
    print_status: Mapped[str] = mapped_column(String, default="unknown")
    source_url: Mapped[str | None] = mapped_column(String, default=None)
    image_url: Mapped[str | None] = mapped_column(String, default=None)
    released_at: Mapped[str | None] = mapped_column(String, index=True, default=None)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
