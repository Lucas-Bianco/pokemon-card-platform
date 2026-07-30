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
