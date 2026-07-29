"""SQLAlchemy models for catalog, prices, and collection."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    source: Mapped[str] = mapped_column(String, index=True)  # "tcgplayer" | "cardmarket"
    variant: Mapped[str] = mapped_column(String, index=True)  # "holofoil", "reverseHolofoil", ...
    low: Mapped[float | None] = mapped_column(Float, default=None)
    mid: Mapped[float | None] = mapped_column(Float, default=None)
    high: Mapped[float | None] = mapped_column(Float, default=None)
    market: Mapped[float | None] = mapped_column(Float, default=None)
    source_updated_at: Mapped[str | None] = mapped_column(String, default=None)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    variant: Mapped[str] = mapped_column(String, default="normal")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    condition: Mapped[str | None] = mapped_column(String, default=None)
    acquired_price: Mapped[float | None] = mapped_column(Float, default=None)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    card: Mapped[Card] = relationship()
