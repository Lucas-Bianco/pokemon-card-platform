"""Sealed-product catalog service (Phase A, roadmap row 09).

Read-only browse/search over the curated `sealed_products` table + an idempotent
seed hook (`ensure_seed`) called once on empty-table startup.

Sacred constraints held:
- `search` uses `func.lower(SealedProduct.name).like(...)` — NEVER `ilike` (SQLite
  portability; the project's standing rule).
- `ensure_seed` is INSERT-only-skip-existing: it never deletes or updates a row
  (never-delete discipline; the catalog is reference data the user may have
  edited — a re-run must not clobber their changes).
- Read paths are pure DB reads; no `data/` writes from routes. The only write is
  the startup seed, and only when the table is empty.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.db.models import SealedProduct

# Allowed enum-ish values for route validation (kept here so the service + the
# routes share one source of truth; NOT enforced at the column level — the column
# is free-text so a future community sync can introduce a new tag without a
# migration; the route 422s on unknown values for v1).
PRODUCT_TYPES: tuple[str, ...] = (
    "booster_pack",
    "booster_box",
    "etb",
    "collection_box",
    "tin",
    "premium_bundle",
    "other",
)
PRINT_STATUSES: tuple[str, ...] = ("in_print", "out_of_print", "unknown")


class SealedCatalogService:
    """Browse/search the sealed-product reference catalog.

    Constructed per-request with the caller's session. `ensure_seed` is the one
    write path (startup-only, idempotent).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- read paths ----

    def count(self) -> int:
        """Total rows in the catalog (used by the empty-seed check)."""
        return self.session.scalar(select(func.count()).select_from(SealedProduct)) or 0

    def search(
        self,
        *,
        query: str | None = None,
        product_type: str | None = None,
        print_status: str | None = None,
        limit: int = 50,
    ) -> list[SealedProduct]:
        """Search the catalog. All filters optional and compose with AND.

        - `query`: case-insensitive substring on name OR era (lower().like()).
        - `product_type` / `print_status`: exact match (route validates the enum).
        - no query + no filters → newest first (released_at desc, nulls last),
          then name asc as a stable tiebreaker.
        """
        stmt = select(SealedProduct)
        q = (query or "").strip()
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(SealedProduct.name).like(like)
                | func.lower(SealedProduct.era).like(like)
            )
        if product_type:
            stmt = stmt.where(SealedProduct.product_type == product_type)
        if print_status:
            stmt = stmt.where(SealedProduct.print_status == print_status)
        if q:
            # Matched search: keep a deterministic order but don't claim relevance.
            stmt = stmt.order_by(SealedProduct.name.asc())
        else:
            # Newest first; null released_at sorts last (honest — undated rows
            # are not pretended to be newest or oldest).
            stmt = stmt.order_by(
                SealedProduct.released_at.desc().nullslast(),
                SealedProduct.name.asc(),
            )
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def get(self, slug: str) -> SealedProduct:
        """Fetch one product by slug. Raises LookupError if unknown (route → 404)."""
        product = self.session.get(SealedProduct, slug)
        if product is None:
            raise LookupError(slug)
        return product

    # ---- seed hook ----

    def ensure_seed(self, products: Iterable[dict[str, Any]]) -> int:
        """Idempotent bulk insert: INSERT only rows whose slug is not already
        present; skip existing. NEVER deletes or updates (never-delete discipline).

        Returns the number of rows actually inserted (0 on a re-run against a
        table that already has these slugs).
        """
        inserted = 0
        for row in products:
            slug = row.get("slug")
            if not slug:
                continue
            if self.session.get(SealedProduct, slug) is not None:
                continue
            self.session.add(
                SealedProduct(
                    slug=slug,
                    name=row["name"],
                    era=row.get("era"),
                    product_type=row["product_type"],
                    msrp=row.get("msrp"),
                    msrp_currency=row.get("msrp_currency", "USD"),
                    print_status=row.get("print_status", "unknown"),
                    source_url=row.get("source_url"),
                    image_url=row.get("image_url"),
                    released_at=row.get("released_at"),
                    source=row.get("source", "manual"),
                )
            )
            inserted += 1
        if inserted:
            self.session.commit()
        return inserted