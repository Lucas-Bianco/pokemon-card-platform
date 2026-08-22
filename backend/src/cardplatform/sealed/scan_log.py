"""Scan-to-log a sealed catalog product (Phase B, roadmap row 09).

Lets the user log a sealed-product purchase straight from a catalog row, by
slug. The service looks the product up in the catalog (via SealedCatalogService)
and creates a SealedPurchase carrying the product's name as `query` and its
`product_type`, so the existing ledger picks it up.

Sacred constraints held:
- The product must exist in the catalog; an unknown slug raises LookupError
  (route -> 404). We never fabricate a product.
- Optional fields (source/listing_url/notes/bought_at) default to None and are
  stored as None when absent — never an empty-string fabrication.
- Additive only: creates a SealedPurchase via the same add/commit/refresh path
  as LedgerService.create_purchase; no new tables, no ALTERs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from cardplatform.db.models import SealedPurchase
from cardplatform.sealed.catalog_service import SealedCatalogService


class SealedScanLogService:
    """Log a sealed-product purchase from a catalog row, by slug.

    Constructed per-request with the caller's session. Delegates catalog lookup
    to SealedCatalogService so the slug-resolution path is the same one the
    browse/search routes use.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def log_from_catalog(
        self,
        slug: str,
        *,
        quantity: int = 1,
        cost_per_unit: float,
        source: str | None = None,
        listing_url: str | None = None,
        notes: str | None = None,
        bought_at: datetime | None = None,
    ) -> SealedPurchase:
        """Look up the SealedProduct by slug and create a SealedPurchase from it.

        The product's `name` becomes the purchase `query` and its `product_type`
        is carried over, so the existing ledger / valuation refresh picks it up
        unchanged. Raises LookupError if the slug is unknown.
        """
        product = SealedCatalogService(self.session).get(slug)  # raises LookupError

        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        if cost_per_unit < 0:
            raise ValueError("cost_per_unit must be >= 0")

        purchase = SealedPurchase(
            query=product.name,
            product_type=product.product_type,
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