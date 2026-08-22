"""MSRP-vs-market comparison for a sealed catalog product (Phase C, roadmap row 09).

For one catalog product (looked up by slug), compare its curated MSRP against the
live eBay sold-comps median — with the SAME honest unavailable/empty flags the
sold-comps route (api.py /sealed/sold-comps) already uses:

- `unavailable` = no listings API key configured (the provider returns [] without
  ever hitting the network). Honest "we can't tell", never a fabricated number.
- `empty` = key is set but eBay returned 0 sold comps. Honest "no recent sales".
- `market_median` is `None` (never 0) when there are no comps.
- `delta` is `None` (never 0) unless BOTH msrp and market_median are real numbers.

Read-only: no `data/` writes, no snapshot persistence. The provider call is the
same one /sealed/sold-comps uses (`fetch_sold_listings_by_query`), so the market
figure here is exactly the figure proven there. Provider failure degrades to []
— this service NEVER raises out of a provider call (mirrors
SealedListingsProvider's never-raise discipline).
"""
from __future__ import annotations

import statistics
from typing import Any

from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.provider import SealedListingsProvider, SealedSoldComp
from cardplatform.config import Settings


class MsrpVsMarketService:
    """Compare a catalog product's curated MSRP to its live sold-comps median.

    Constructed per-request with the caller's session + settings + provider
    (the controller builds it the same way `SealedDealEngine` is built —
    `provider = EbayListingsProvider(settings)` then the service).
    """

    def __init__(
        self,
        session: Any,
        settings: Settings,
        provider: SealedListingsProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider

    def compare(self, slug: str) -> dict:
        """Return the MSRP-vs-market comparison for one product slug.

        Raises LookupError if the slug is unknown (the route maps that to 404).
        Never raises out of the provider call — a provider failure degrades to
        [] (honest empty), never an exception.
        """
        product = SealedCatalogService(self.session).get(slug)  # LookupError if missing

        msrp = product.msrp
        msrp_currency = product.msrp_currency

        # Same provider call /sealed/sold-comps uses. Never raises — degrade to []
        # on any provider failure (mirrors the SealedListingsProvider contract).
        try:
            comps: list[SealedSoldComp] = self.provider.fetch_sold_listings_by_query(
                product.name, self.settings.sealed_sold_comp_limit
            )
        except Exception:
            comps = []

        # Honest unavailable/empty flags — mirror api.py /sealed/sold-comps exactly:
        # no key -> unavailable; key set but 0 comps -> empty.
        key_set = bool(self.settings.listings_api_key)
        unavailable = not key_set
        empty = key_set and not comps

        comp_prices = [c.price for c in comps if c.price is not None]
        market_median = statistics.median(comp_prices) if comp_prices else None

        # Source provenance travels with the figure so the UI can say where it came
        # from. Sold comps carry no per-sale source_updated_at stamp, so it's None.
        if comps:
            market_source = comps[0].source
            market_source_updated_at = None
        else:
            market_source = None
            market_source_updated_at = None

        delta = (
            msrp - market_median
            if msrp is not None and market_median is not None
            else None
        )

        return {
            "slug": slug,
            "name": product.name,
            "msrp": msrp,
            "msrp_currency": msrp_currency,
            "market_median": market_median,
            "market_source": market_source,
            "market_source_updated_at": market_source_updated_at,
            "sold_comps_count": len(comps),
            "delta": delta,
            "unavailable": unavailable,
            "empty": empty,
        }