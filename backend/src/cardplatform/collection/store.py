"""Owns collection rows and values them against the latest recorded prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CollectionItem
from cardplatform.prices.service import PriceService


@dataclass(frozen=True)
class Valuation:
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


@dataclass(frozen=True)
class PortfolioItem:
    """One holding enriched with its resolved market price and unrealized P/L.

    market_price/unrealized are None when the item is unpriced; unrealized is also None
    when there is no cost basis, because a price with no purchase cost is not a gain.
    """

    id: int
    card_id: str
    card_name: str
    set_id: str
    set_name: str
    variant: str
    quantity: int
    acquired_price: float | None
    acquired_at: datetime | None
    condition: str | None
    notes: str | None
    market_price: float | None
    market_source: str | None
    market_source_updated_at: str | None
    unrealized: float | None
    priced: bool


@dataclass(frozen=True)
class Allocation:
    set_id: str
    set_name: str
    market_value: float
    cost_basis: float
    item_count: int


@dataclass(frozen=True)
class PortfolioSummary:
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int
    priced_items: int
    allocation: list[Allocation]
    top_gainers: list[PortfolioItem]
    top_losers: list[PortfolioItem]


@dataclass(frozen=True)
class Portfolio:
    summary: PortfolioSummary
    items: list[PortfolioItem]


@dataclass(frozen=True)
class InsuranceLine:
    """One holding's replacement-value provenance for a printable insurance schedule.

    low/market/high are the raw figures from the same proven snapshot the rest of the
    app uses (None when the snapshot omits them, or when the holding is unpriced).
    `priced` is False when there is no usable market figure — such a line still appears
    in the schedule (so nothing is silently dropped) but contributes to no band total.
    """

    card_id: str
    card_name: str
    set_name: str
    variant: str
    quantity: int
    low: float | None
    market: float | None
    high: float | None
    source: str | None
    source_updated_at: str | None
    priced: bool


@dataclass(frozen=True)
class InsuranceValue:
    """Replacement-value bands for the collection, from proven price snapshots.

    conservative = low (fallback to market when low is missing); median = market;
    aggressive = high (fallback to market when high is missing). Unpriced cards are
    excluded from all three totals and counted in unpriced_items — never guessed at
    $0. The schedule lists every holding (priced and unpriced) with per-line source
    and source_updated_at so a printed schedule never shows a number without saying
    where it came from.
    """

    conservative: float
    median: float
    aggressive: float
    priced_items: int
    unpriced_items: int
    schedule: list[InsuranceLine]
    caveat: str


@dataclass(frozen=True)
class HoldingShare:
    """One holding's slice of the collection's *priced* value.

    market_value = market x quantity. share = market_value / priced_total (0.0
    when there is no priced value to divide). cumulative_share is the running
    total of share down the ranked list — the input to the concentration ratios.
    """

    card_id: str
    card_name: str
    set_name: str
    variant: str
    quantity: int
    market_value: float
    share: float
    cumulative_share: float


@dataclass(frozen=True)
class BucketShare:
    """One grouping (by rarity / supertype / set) of the collection's value.

    market_value is the sum of priced holdings in the bucket (0.0 when the
    bucket's holdings are all unpriced). share = market_value / priced_total.
    holdings counts CollectionItem rows; quantity sums their quantities. A
    bucket with holdings but no priced value still appears — share 0.0, never
    silently dropped and never estimated at $0.
    """

    label: str
    market_value: float
    share: float
    holdings: int
    quantity: int


@dataclass(frozen=True)
class Concentration:
    """How few holdings carry most of the priced value. Every field is None when
    there is no priced value (a collection with 0 priced holdings has nothing to
    concentrate); priced_holdings is always a real count. cards_for_XX is the
    smallest number of top holdings whose cumulative share reaches XX% — since
    the full priced collection sums to 100%, every threshold is reachable once
    priced_total > 0, so the None fields signal 'no priced value', not an
    unreachable threshold."""

    top_share: float | None
    cards_for_50: int | None
    cards_for_80: int | None
    cards_for_90: int | None
    priced_holdings: int


@dataclass(frozen=True)
class Diversification:
    """Concentration + diversification of the collection's *priced* value.

    priced_total is the sum of market x quantity across priced holdings only;
    unpriced cards are counted in unpriced_items and excluded from every total
    and every share, never estimated at $0. top_holdings are the (up to) 10
    largest priced holdings. by_rarity / by_supertype / by_set group every
    holding (priced and unpriced) so an all-unpriced bucket still shows up at
    share 0.0.
    """

    priced_total: float
    priced_items: int
    unpriced_items: int
    total_items: int
    top_holdings: list[HoldingShare]
    concentration: Concentration
    by_rarity: list[BucketShare]
    by_supertype: list[BucketShare]
    by_set: list[BucketShare]
    caveat: str


_INSURANCE_CAVEAT = (
    "Replacement-value bands from the same proven price snapshot the rest of the app "
    "uses (TCGplayer market reference via pokemontcg.io, or Cardmarket aggregate as "
    "fallback). Unpriced cards are excluded from the totals, never guessed at $0. "
    "An indicative estimate, not a binding appraisal."
)


_DIVERSIFICATION_CAVEAT = (
    "Concentration of the collection's *priced* value. Shares are computed against "
    "the sum of priced holdings only; unpriced cards are counted in unpriced_items "
    "and excluded from every total and every share, never estimated at $0. A high "
    "concentration (a few cards carrying most of the value) is a risk flag, not a "
    "verdict — diversification is descriptive, never a recommendation to trade."
)


class CollectionStore:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.prices = PriceService(session)

    def add(
        self,
        card_id: str,
        variant: str = "normal",
        quantity: int = 1,
        acquired_price: float | None = None,
        condition: str | None = None,
        notes: str | None = None,
    ) -> CollectionItem:
        """Add copies of a card. Re-adding the same (card_id, variant) tops up the
        existing row so a collection holds one row per printing, not one per purchase."""
        if self.session.get(Card, card_id) is None:
            raise ValueError(f"unknown card: {card_id!r}")

        item = self._find(card_id, variant)
        if item is None:
            item = CollectionItem(
                card_id=card_id,
                variant=variant,
                quantity=quantity,
                acquired_price=acquired_price,
                condition=condition,
                notes=notes,
                acquired_at=datetime.now(timezone.utc),
            )
            self.session.add(item)
        else:
            item.quantity += quantity
        self.session.commit()
        return item

    def remove(self, card_id: str, variant: str = "normal", quantity: int = 1) -> None:
        """Remove copies. Removing more than held, or a card never held, is a no-op
        rather than an error — callers should not have to check first."""
        item = self._find(card_id, variant)
        if item is None:
            return

        item.quantity -= quantity
        if item.quantity <= 0:
            self.session.delete(item)
        self.session.commit()

    def list_items(self) -> list[CollectionItem]:
        return list(
            self.session.scalars(select(CollectionItem).order_by(CollectionItem.id)).all()
        )

    def total_value(self) -> Valuation:
        """Value the collection conservatively: an item we cannot price contributes
        nothing to market value and is counted, never estimated from a neighbour."""
        market_value = 0.0
        cost_basis = 0.0
        unpriced_items = 0

        for item in self.list_items():
            if item.acquired_price is not None:
                cost_basis += item.acquired_price * item.quantity

            snapshot = self.prices.latest_price(item.card_id, item.variant)
            if snapshot is None or snapshot.market is None:
                unpriced_items += 1
                continue
            market_value += snapshot.market * item.quantity

        return Valuation(
            market_value=market_value,
            cost_basis=cost_basis,
            unrealized=market_value - cost_basis,
            unpriced_items=unpriced_items,
        )

    def insurance_value(self) -> InsuranceValue:
        """Replacement-value bands for insurance: conservative (low), median (market),
        aggressive (high), each summed across priced holdings × quantity.

        Uses the same `latest_price` resolution as total_value (TCGplayer snapshot
        preferred, Cardmarket aggregate fallback). low/high fall back to market when
        the snapshot omits them, so a holding with only a market figure still
        contributes to all three bands at its best-known value. Unpriced holdings
        (no snapshot or market is None) are excluded from every total and counted in
        unpriced_items — never estimated at $0. The schedule lists every holding with
        per-line source + source_updated_at (the "" sentinel coerced to None).
        """
        conservative = 0.0
        median = 0.0
        aggressive = 0.0
        priced_items = 0
        unpriced_items = 0
        schedule: list[InsuranceLine] = []

        for item in self.list_items():
            snapshot = self.prices.latest_price(item.card_id, item.variant)
            market = snapshot.market if snapshot is not None else None
            low = snapshot.low if snapshot is not None else None
            high = snapshot.high if snapshot is not None else None
            priced = market is not None

            if priced:
                conservative += (low if low is not None else market) * item.quantity
                median += market * item.quantity
                aggressive += (high if high is not None else market) * item.quantity
                priced_items += 1
                source = snapshot.source
                source_updated_at = snapshot.source_updated_at or None
            else:
                unpriced_items += 1
                source = None
                source_updated_at = None

            schedule.append(
                InsuranceLine(
                    card_id=item.card_id,
                    card_name=item.card.name,
                    set_name=item.card.card_set.name,
                    variant=item.variant,
                    quantity=item.quantity,
                    low=low,
                    market=market,
                    high=high,
                    source=source,
                    source_updated_at=source_updated_at,
                    priced=priced,
                )
            )

        return InsuranceValue(
            conservative=conservative,
            median=median,
            aggressive=aggressive,
            priced_items=priced_items,
            unpriced_items=unpriced_items,
            schedule=schedule,
            caveat=_INSURANCE_CAVEAT,
        )

    def diversification(self) -> Diversification:
        """Concentration + diversification of the collection's *priced* value.

        One pass over every holding resolves its priced market value via the same
        `latest_price` the rest of the app uses. priced_total is the sum of
        market x quantity across priced holdings; unpriced holdings are counted in
        unpriced_items and excluded from every total and every share, never
        estimated at $0. top_holdings ranks the (up to) 10 largest priced holdings
        with share + cumulative_share. concentration gives the smallest number of
        top holdings reaching 50/80/90% of priced value (None when priced_total is
        0 or the threshold is unreachable). by_rarity / by_supertype / by_set group
        every holding — an all-unpriced bucket still appears at share 0.0.
        """
        rows = self.list_items()
        priced_total = 0.0
        unpriced_items = 0
        recs: list[tuple[CollectionItem, float | None]] = []
        for row in rows:
            snapshot = self.prices.latest_price(row.card_id, row.variant)
            market = snapshot.market if snapshot is not None else None
            if market is None:
                unpriced_items += 1
                recs.append((row, None))
            else:
                value = market * row.quantity
                priced_total += value
                recs.append((row, value))

        priced_recs = sorted(
            ((row, mv) for row, mv in recs if mv is not None),
            key=lambda rm: rm[1],
            reverse=True,
        )

        top_holdings: list[HoldingShare] = []
        cumulative = 0.0
        for row, value in priced_recs[:10]:
            share = value / priced_total if priced_total else 0.0
            cumulative += share
            top_holdings.append(
                HoldingShare(
                    card_id=row.card_id,
                    card_name=row.card.name,
                    set_name=row.card.card_set.name,
                    variant=row.variant,
                    quantity=row.quantity,
                    market_value=value,
                    share=share,
                    cumulative_share=cumulative,
                )
            )

        if priced_total > 0 and priced_recs:
            running = 0.0
            cards_for_50 = cards_for_80 = cards_for_90 = None
            # Epsilon absorbs floating-point drift so the count matches the
            # rounded cumulative share the UI shows (e.g. 0.7 + 0.2 accumulates
            # to 0.8999…, which must still count as reaching the 90% threshold).
            eps = 1e-9
            for index, (_, value) in enumerate(priced_recs, start=1):
                running += value / priced_total
                if cards_for_50 is None and running >= 0.5 - eps:
                    cards_for_50 = index
                if cards_for_80 is None and running >= 0.8 - eps:
                    cards_for_80 = index
                if cards_for_90 is None and running >= 0.9 - eps:
                    cards_for_90 = index
            top_share = priced_recs[0][1] / priced_total
            concentration = Concentration(
                top_share=top_share,
                cards_for_50=cards_for_50,
                cards_for_80=cards_for_80,
                cards_for_90=cards_for_90,
                priced_holdings=len(priced_recs),
            )
        else:
            concentration = Concentration(
                top_share=None,
                cards_for_50=None,
                cards_for_80=None,
                cards_for_90=None,
                priced_holdings=len(priced_recs),
            )

        by_rarity = self._diversification_buckets(
            recs, priced_total, key=lambda r: r.card.rarity or "Unknown"
        )
        by_supertype = self._diversification_buckets(
            recs, priced_total, key=lambda r: r.card.supertype or "Unknown"
        )
        by_set = self._diversification_buckets(
            recs, priced_total, key=lambda r: r.card.card_set.name
        )

        return Diversification(
            priced_total=priced_total,
            priced_items=len(priced_recs),
            unpriced_items=unpriced_items,
            total_items=len(rows),
            top_holdings=top_holdings,
            concentration=concentration,
            by_rarity=by_rarity,
            by_supertype=by_supertype,
            by_set=by_set,
            caveat=_DIVERSIFICATION_CAVEAT,
        )

    @staticmethod
    def _diversification_buckets(
        recs: list[tuple[CollectionItem, float | None]],
        priced_total: float,
        *,
        key,
    ) -> list[BucketShare]:
        """Group holdings by ``key(row)`` (rarity / supertype / set name). Each
        bucket accumulates market_value from its priced holdings only (0.0 when
        all its holdings are unpriced), counts holdings and sums quantities. A
        bucket with holdings but no priced value still appears — share 0.0,
        never dropped and never estimated at $0. Sorted by market value desc."""
        buckets: dict[str, dict[str, float]] = {}
        for row, value in recs:
            label = key(row)
            bucket = buckets.setdefault(
                label, {"market_value": 0.0, "holdings": 0, "quantity": 0}
            )
            bucket["holdings"] += 1
            bucket["quantity"] += row.quantity
            if value is not None:
                bucket["market_value"] += value

        shares = [
            BucketShare(
                label=label,
                market_value=b["market_value"],
                share=b["market_value"] / priced_total if priced_total else 0.0,
                holdings=int(b["holdings"]),
                quantity=int(b["quantity"]),
            )
            for label, b in buckets.items()
        ]
        shares.sort(key=lambda s: s.market_value, reverse=True)
        return shares

    def portfolio(self) -> Portfolio:
        """The collection as priced holdings plus a summary: per-item market value and
        unrealized P/L, allocation by set, and top movers. All pricing stays server-side
        — the frontend never resolves 'the latest price' itself."""
        items = [self._portfolio_item(row) for row in self.list_items()]
        return Portfolio(summary=self._summary(items), items=items)

    def summary(self) -> PortfolioSummary:
        """Summary without the full holdings list (a lightweight portfolio read)."""
        items = [self._portfolio_item(row) for row in self.list_items()]
        return self._summary(items)

    def set_cost_basis(
        self,
        item_id: int,
        acquired_price: float | None,
        acquired_at: datetime | None = None,
        condition: str | None = None,
        notes: str | None = None,
    ) -> CollectionItem:
        """Backfill or correct the purchase details on an existing holding. acquired_price
        is set unconditionally (pass None to clear it); the other fields update only when
        provided, so a partial PATCH leaves them intact."""
        item = self.session.get(CollectionItem, item_id)
        if item is None:
            raise ValueError(f"unknown item: {item_id!r}")
        item.acquired_price = acquired_price
        if acquired_at is not None:
            item.acquired_at = acquired_at
        if condition is not None:
            item.condition = condition
        if notes is not None:
            item.notes = notes
        self.session.commit()
        return item

    def _portfolio_item(self, row: CollectionItem) -> PortfolioItem:
        snapshot = self.prices.latest_price(row.card_id, row.variant)
        market = snapshot.market if snapshot is not None else None
        priced = market is not None
        if market is not None and row.acquired_price is not None:
            unrealized = (market - row.acquired_price) * row.quantity
        else:
            unrealized = None
        return PortfolioItem(
            id=row.id,
            card_id=row.card_id,
            card_name=row.card.name,
            set_id=row.card.set_id,
            set_name=row.card.card_set.name,
            variant=row.variant,
            quantity=row.quantity,
            acquired_price=row.acquired_price,
            acquired_at=row.acquired_at,
            condition=row.condition,
            notes=row.notes,
            market_price=market,
            market_source=snapshot.source if priced else None,
            market_source_updated_at=snapshot.source_updated_at if priced else None,
            unrealized=unrealized,
            priced=priced,
        )

    def _summary(self, items: list[PortfolioItem]) -> PortfolioSummary:
        market_value = sum(
            i.market_price * i.quantity for i in items if i.market_price is not None
        )
        cost_basis = sum(
            i.acquired_price * i.quantity for i in items if i.acquired_price is not None
        )
        unpriced_items = sum(1 for i in items if not i.priced)
        priced_items = sum(1 for i in items if i.priced)

        allocation = self._allocation(items)
        movers = [i for i in items if i.unrealized is not None]
        top_gainers = sorted(movers, key=lambda i: i.unrealized, reverse=True)[:3]
        top_losers = sorted(movers, key=lambda i: i.unrealized)[:3]

        return PortfolioSummary(
            market_value=market_value,
            cost_basis=cost_basis,
            unrealized=market_value - cost_basis,
            unpriced_items=unpriced_items,
            priced_items=priced_items,
            allocation=allocation,
            top_gainers=top_gainers,
            top_losers=top_losers,
        )

    @staticmethod
    def _allocation(items: list[PortfolioItem]) -> list[Allocation]:
        """Group holdings by set, summing market value and cost basis. Unpriced items
        contribute 0 to market value (never estimated) but still count toward item_count
        and cost basis, so allocation reflects real exposure."""
        by_set: dict[str, Allocation] = {}
        for i in items:
            mv = (i.market_price or 0.0) * i.quantity
            cb = (i.acquired_price or 0.0) * i.quantity
            existing = by_set.get(i.set_id)
            if existing is None:
                by_set[i.set_id] = Allocation(i.set_id, i.set_name, mv, cb, 1)
            else:
                by_set[i.set_id] = Allocation(
                    existing.set_id,
                    existing.set_name,
                    existing.market_value + mv,
                    existing.cost_basis + cb,
                    existing.item_count + 1,
                )
        return sorted(by_set.values(), key=lambda a: a.market_value, reverse=True)

    def _find(self, card_id: str, variant: str) -> CollectionItem | None:
        return self.session.scalars(
            select(CollectionItem).where(
                CollectionItem.card_id == card_id,
                CollectionItem.variant == variant,
            )
        ).first()
