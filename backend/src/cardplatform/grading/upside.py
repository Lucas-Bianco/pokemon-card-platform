"""Grading-upside service: the price spread between raw and graded copies.

This is NOT a grade prediction. Predicting P(PSA 10) for a specific card requires
the grade predictor we do not yet have (Phase 3c). What this service computes is
the simpler, honest question the user can already act on: given the current raw
market price, the current PSA-9 / PSA-10 market prices, and the bulk grading fee,
what is the dollar upside to a PSA-10?

The shape is deliberately a spread, never a verdict. Every price field is null
when the underlying snapshot is missing — never a fabricated $0 (the project's
sacred convention: see frontend PortfolioView.tsx / PriceChart.tsx, which render
an em dash and "no market price" rather than a flat zero). `upside_to_10` is the
one number that would be confidently-wrong if fabricated, so it is null unless
BOTH the raw market price and the PSA-10 market price are present.

`graded_prices_unavailable` is true only when BOTH psa9 and psa10 are null. The
frontend uses it to render "graded prices unavailable — set a graded-price
provider key" instead of a misleading panel of zeroes.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cardplatform.config import settings
from cardplatform.prices.graded_service import GradedPriceService
from cardplatform.prices.service import PriceService


def _price_dict(snapshot) -> dict | None:
    """Snapshot -> the three fields the spread needs, or None when missing.

    market, source, and source_updated_at travel together so the UI can say where
    a number came from and how old it is, instead of implying everything is
    current. Returns None (never a dict with a 0.0 market) when there is no
    snapshot — the honest empty state.
    """
    if snapshot is None:
        return None
    return {
        "market": snapshot.market,
        "source": snapshot.source,
        "source_updated_at": snapshot.source_updated_at,
    }


class GradingUpsideService:
    """Computes the raw-vs-graded price spread for one card and variant.

    Reads only — never fetches. Constructs PriceService / GradedPriceService
    without providers (the sanctioned read-only construction) and delegates to
    latest_price / latest_graded, the only sanctioned price resolvers. Never
    resolves a price ad hoc or fabricates a number for a missing snapshot.
    """

    def __init__(
        self,
        session: Session,
        price_service: PriceService | None = None,
        graded_service: GradedPriceService | None = None,
    ) -> None:
        # Default-construct the read-only services when callers don't pass them
        # (mirrors how PriceService is built in api.py's read-only endpoints).
        self.price_service = price_service or PriceService(session)
        self.graded_service = graded_service or GradedPriceService(session)

    def upside(self, card_id: str, variant: str) -> dict:
        """The grading-upside spread for one (card_id, variant).

        Returns exactly:
            {
              "card_id", "variant",
              "raw_price":  {market, source, source_updated_at} | null,
              "psa9":       {market, source, source_updated_at} | null,
              "psa10":      {market, source, source_updated_at} | null,
              "grading_fee": float,                          # always present
              "upside_to_10": float | null,                  # null unless both raw+psa10 present
              "graded_prices_unavailable": bool,              # true only when psa9 AND psa10 null
            }

        `upside_to_10` is `psa10.market - raw.market - grading_fee`, computed
        ONLY when both raw_price.market and psa10.market are non-None. Either
        input missing => null. Never a fabricated number from missing inputs.
        """
        raw = self.price_service.latest_price(card_id, variant)
        psa9 = self.graded_service.latest_graded(card_id, variant, 9.0, grader="PSA")
        psa10 = self.graded_service.latest_graded(card_id, variant, 10.0, grader="PSA")

        raw_dict = _price_dict(raw)
        psa9_dict = _price_dict(psa9)
        psa10_dict = _price_dict(psa10)

        # upside_to_10 is the core "never confidently-wrong" value: it requires
        # BOTH the raw market price and the PSA-10 market price. Either missing
        # => null, never a fake number from a missing input.
        upside_to_10: float | None = None
        if (
            raw_dict is not None
            and psa10_dict is not None
            and raw_dict["market"] is not None
            and psa10_dict["market"] is not None
        ):
            upside_to_10 = psa10_dict["market"] - raw_dict["market"] - settings.grading_fee

        # graded_prices_unavailable signals the frontend to show the "set a
        # graded-price provider key" empty state instead of a panel of zeroes.
        # True ONLY when both graded tiers are absent — a lone psa9 is enough to
        # prove graded prices ARE available (just not a 10), so it stays false.
        graded_prices_unavailable = psa9_dict is None and psa10_dict is None

        return {
            "card_id": card_id,
            "variant": variant,
            "raw_price": raw_dict,
            "psa9": psa9_dict,
            "psa10": psa10_dict,
            "grading_fee": settings.grading_fee,
            "upside_to_10": upside_to_10,
            "graded_prices_unavailable": graded_prices_unavailable,
        }