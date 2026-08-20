"""Sealed purchase ledger + profit tracker.

Reseller-facing: log sealed boxes/packs bought, fetch current market value per unit
(median of recent eBay sold comps via the 05c sealed provider), store append-only
valuations, and compute live profit.

Sacred constraints held:
- Profit reads the latest persisted SealedValuation (never resolves a price ad hoc).
- Refresh is the only write path for valuations and it INSERTs (append-only, never update);
  latest = max(id) per purchase.
- No eBay key / no comps / provider error -> no valuation inserted (honest), never raises.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import SealedPurchase, SealedValuation
from cardplatform.sealed.provider import SealedListingsProvider


@dataclass(frozen=True)
class LedgerEntry:
    """One row of the ledger view — a purchase joined with its latest valuation +
    read-only profit math. Nulls are honest (unvalued), never $0."""

    id: int
    query: str
    product_type: str | None
    quantity: int
    cost_per_unit: float
    total_cost: float
    source: str | None
    listing_url: str | None
    notes: str | None
    bought_at: datetime
    created_at: datetime
    value_per_unit: float | None
    total_current_value: float | None
    profit: float | None
    profit_pct: float | None
    market_fetched_at: datetime | None
    market_source: str | None
    valued: bool


@dataclass(frozen=True)
class ValuationRefreshResult:
    valued: int
    skipped_no_comps: int
    skipped_no_key: bool


class LedgerService:
    """CRUD + on-demand valuation refresh + read-only profit. The provider is used only by
    refresh_*; list_ledger is pure DB read."""

    def __init__(
        self,
        session: Session,
        provider: SealedListingsProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or default_settings
        if provider is None:
            # Lazy import to avoid a hard import cycle at module load.
            from cardplatform.prices.ebay_listings import EbayListingsProvider

            provider = EbayListingsProvider(self.settings)
        self.provider = provider

    # ---- CRUD ----

    def create_purchase(
        self,
        *,
        query: str,
        product_type: str | None = None,
        quantity: int = 1,
        cost_per_unit: float,
        source: str | None = None,
        listing_url: str | None = None,
        notes: str | None = None,
        bought_at: datetime | None = None,
    ) -> SealedPurchase:
        q = (query or "").strip()
        if not q:
            raise ValueError("query is required")
        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        if cost_per_unit < 0:
            raise ValueError("cost_per_unit must be >= 0")
        purchase = SealedPurchase(
            query=q,
            product_type=product_type,
            quantity=quantity,
            cost_per_unit=cost_per_unit,
            source=source,
            listing_url=listing_url,
            notes=notes,
            bought_at=bought_at,
        )
        self.session.add(purchase)
        self.session.commit()
        self.session.refresh(purchase)
        return purchase

    def get_purchase(self, purchase_id: int) -> SealedPurchase | None:
        return self.session.get(SealedPurchase, purchase_id)

    def delete_purchase(self, purchase_id: int) -> bool:
        purchase = self.session.get(SealedPurchase, purchase_id)
        if purchase is None:
            return False
        # Explicit cascade — do not rely on a SQLite FK-cascade pragma being enabled.
        self.session.query(SealedValuation).filter(
            SealedValuation.purchase_id == purchase_id
        ).delete(synchronize_session=False)
        self.session.delete(purchase)
        self.session.commit()
        return True

    # ---- valuations ----

    def latest_valuation(self, purchase_id: int) -> SealedValuation | None:
        stmt = (
            select(SealedValuation)
            .where(SealedValuation.purchase_id == purchase_id)
            .order_by(SealedValuation.id.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def refresh_valuation(self, purchase_id: int) -> SealedValuation | None:
        purchase = self.session.get(SealedPurchase, purchase_id)
        if purchase is None:
            return None
        try:
            comps = self.provider.fetch_sold_listings_by_query(
                purchase.query, self.settings.sealed_sold_comp_limit
            )
        except Exception:  # providers never raise in practice; be defensive anyway.
            return None
        prices = [c.price for c in comps if c.price is not None]
        if not prices:
            return None  # no comps -> no snapshot, honest
        value = statistics.median(prices)
        v = SealedValuation(
            purchase_id=purchase.id,
            value_per_unit=value,
            source="ebay_sold_median",
            comp_count=len(prices),
        )
        self.session.add(v)
        self.session.commit()
        self.session.refresh(v)
        return v

    def refresh_all(self) -> ValuationRefreshResult:
        purchases = self.session.execute(
            select(SealedPurchase).order_by(SealedPurchase.id.asc())
        ).scalars().all()
        # No eBay key -> the real provider returns [] for every query, so everything is
        # skipped. The diagnostic flag is True only when that's the actual outcome (no key
        # AND nothing valued); a provider that returns comps anyway (e.g. a fake in tests,
        # or a future non-eBay adapter) is not "skipped for lack of a key".
        key_set = bool(getattr(self.settings, "listings_api_key", None))
        valued = 0
        skipped_no_comps = 0
        for p in purchases:
            v = self.refresh_valuation(p.id)
            if v is not None:
                valued += 1
            else:
                skipped_no_comps += 1
        return ValuationRefreshResult(
            valued=valued,
            skipped_no_comps=skipped_no_comps,
            skipped_no_key=(not key_set) and valued == 0,
        )

    # ---- read-only profit ----

    def list_ledger(self) -> list[LedgerEntry]:
        purchases = self.session.execute(
            select(SealedPurchase).order_by(SealedPurchase.bought_at.desc())
        ).scalars().all()
        entries: list[LedgerEntry] = []
        for p in purchases:
            latest = self.latest_valuation(p.id)
            total_cost = p.quantity * p.cost_per_unit
            value_per_unit = latest.value_per_unit if latest is not None else None
            total_current_value = (
                value_per_unit * p.quantity if value_per_unit is not None else None
            )
            profit = (
                total_current_value - total_cost
                if total_current_value is not None
                else None
            )
            profit_pct = (
                profit / total_cost
                if profit is not None and total_cost > 0
                else None
            )
            entries.append(
                LedgerEntry(
                    id=p.id,
                    query=p.query,
                    product_type=p.product_type,
                    quantity=p.quantity,
                    cost_per_unit=p.cost_per_unit,
                    total_cost=total_cost,
                    source=p.source,
                    listing_url=p.listing_url,
                    notes=p.notes,
                    bought_at=p.bought_at,
                    created_at=p.created_at,
                    value_per_unit=value_per_unit,
                    total_current_value=total_current_value,
                    profit=profit,
                    profit_pct=profit_pct,
                    market_fetched_at=latest.fetched_at if latest is not None else None,
                    market_source=latest.source if latest is not None else None,
                    valued=latest is not None,
                )
            )
        return entries