import { useCallback, useEffect, useState } from "react";

import { getCard, getDeals, getPriceHistory, refreshListings } from "../api/client";
import type { CardSearchResult, DealAssessment, Listing, PricePoint } from "../api/types";
import { formatMoney } from "../lib/format";
import AddToBinderButton from "./AddToBinderButton";
import AddToWantsButton from "./AddToWantsButton";
import GradingStudio from "./GradingStudio";
import GradingUpside from "./GradingUpside";
import TradeUp from "./TradeUp";
import PriceChart from "./PriceChart";
import PriceLine from "./PriceLine";
import SoldComps from "./SoldComps";

interface Props {
  cardId: string;
  variant?: string;
  onBack: () => void;
  onWatchCard?: (card: { cardId: string; variant?: string }) => void;
}

// Loading + error + retry for the card fetch — the gating load. GradingUpside
// and PriceLine fetch their own data (reused, not duplicated), so CardDetail
// only owns the card body, the price history, and the listings.
export default function CardDetail({ cardId, variant = "normal", onBack, onWatchCard }: Props) {
  const [card, setCard] = useState<CardSearchResult | null>(null);
  const [cardError, setCardError] = useState(false);
  const [loading, setLoading] = useState(true);

  const [history, setHistory] = useState<PricePoint[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [listings, setListings] = useState<Listing[]>([]);
  const [listingsUnavailable, setListingsUnavailable] = useState(false);
  const [listingsLoading, setListingsLoading] = useState(true);
  const [listingsError, setListingsError] = useState<string | null>(null);

  // Deal assessments for the active listings — matched by listing_id to attach
  // a compact deal chip to each row. Enrichment, not gating: a failed deals
  // fetch never hides the listings themselves, so it resolves to [] (no chip)
  // rather than an error that would mask the honest listing list.
  const [deals, setDeals] = useState<DealAssessment[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setCardError(false);
    setListingsLoading(true);
    setListingsError(null);
    setHistoryError(null);

    // The card fetch is gating: without it there is no name/set to show. Listings
    // and history are independent and may fail without hiding the whole screen.
    try {
      const c = await getCard(cardId);
      setCard(c);
    } catch {
      setCardError(true);
      setLoading(false);
      setListingsLoading(false);
      return;
    }
    setLoading(false);

    // Listings refresh (POST) — honest empty states differ by listings_unavailable.
    refreshListings(cardId, variant)
      .then((res) => {
        setListings(res.listings);
        setListingsUnavailable(res.listings_unavailable);
      })
      .catch((err) => {
        setListingsError(err instanceof Error ? err.message : "Could not load listings.");
      })
      .finally(() => setListingsLoading(false));

    // Price history for the chart. Null points render PriceChart's own empty state.
    getPriceHistory(cardId, variant)
      .then((h) => setHistory(h.points))
      .catch((err) => {
        setHistoryError(err instanceof Error ? err.message : "Could not load price history.");
      });

    // Deal assessments for the active listings. Enrichment only — a failure
    // leaves the listings visible with no chip, never an error that hides them.
    getDeals(cardId, variant)
      .then((res) => setDeals(res.deals))
      .catch(() => setDeals([]));
  }, [cardId, variant]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  if (loading) {
    return (
      <section className="card-detail">
        <button className="link card-back" onClick={onBack}>
          ← Back
        </button>
        <div className="skeleton skeleton-block" aria-label="Loading card" />
      </section>
    );
  }

  if (cardError) {
    return (
      <section className="card-detail">
        <button className="link card-back" onClick={onBack}>
          ← Back
        </button>
        <p className="error">Couldn't load this card.</p>
        <button className="primary" onClick={() => void load()}>
          Retry
        </button>
      </section>
    );
  }

  const c = card!;
  return (
    <section className="card-detail">
      <button className="link card-back" onClick={onBack}>
        ← Back
      </button>

      <div className="card-detail-art">
        {c.image_large || c.image_small ? (
          <img
            src={c.image_large ?? c.image_small ?? undefined}
            alt={c.name}
            className="card-detail-image"
          />
        ) : (
          <div className="card-detail-image placeholder" aria-hidden="true" />
        )}
      </div>

      <div className="card-detail-head">
        <h2>{c.name}</h2>
        <p className="card-meta">
          {c.set_name} · #{c.number}
        </p>
      </div>

      <div className="card-detail-price">
        <PriceLine cardId={cardId} variant={variant} initial={null} showBand />
      </div>

      {/* Two honest figures that can differ. The number above is a market
          reference (an asking price, TCGplayer-derived via pokemontcg.io).
          The eBay sales below are proven transactions. The two often
          disagree, and that gap is the honest signal — not a bug to paper
          over. If the reference is unavailable, the sales may still have
          evidence. */}
      <p className="price-provenance muted small">
        The figure above is a market reference (an ask). The eBay sales below are proven
        transactions — two honest figures that can differ. If the reference is unavailable, the
        sales may still have evidence.
      </p>

      {/* Evidence backing the raw market price above. Sold comps fetch their
          own data (reused, not duplicated) — they're evidence, not a price. */}
      <SoldComps cardId={cardId} variant={variant} />

      {/* Reused — not duplicated. The spread panel fetches its own data. */}
      <GradingUpside cardId={cardId} variant={variant} />

      {/* Row 19 — trade-up / sell-now simulator. Reused, not duplicated: fetches
          its own assessment. A per-card exit-strategy tool, card-gated like the
          spread panel above. */}
      <TradeUp cardId={cardId} variant={variant} />

      {/* Sub-score-only self-assessment for a card you own. No scan -> centering
          unmeasured; the user rates corners/edges/surface for an estimated band.
          A calculator of their inputs, not a prediction from the image. */}
      <GradingStudio centering={null} grader="PSA" />

      {historyError ? (
        <p className="error small">{historyError}</p>
      ) : history === null ? (
        <div className="skeleton skeleton-block" aria-label="Loading price history" />
      ) : (
        <PriceChart points={history} variant={variant} />
      )}

      <div className="card-detail-listings">
        <h3>Active listings</h3>
        {listingsError && <p className="error small">{listingsError}</p>}
        {!listingsError && listingsLoading && (
          <p className="muted small">Checking listings…</p>
        )}
        {!listingsError && !listingsLoading && listings.length === 0 && listingsUnavailable && (
          <p className="muted small">
            Set a listings source key to detect restocks and new listings.
          </p>
        )}
        {!listingsError && !listingsLoading && listings.length === 0 && !listingsUnavailable && (
          <p className="muted small">No active listings right now.</p>
        )}
        {!listingsError && !listingsLoading && listings.length > 0 && (
          <ul className="listing-list">
            {listings.map((l) => {
              const deal = deals.find((d) => d.listing_id === l.listing_id);
              return (
                <li key={l.listing_id} className="listing-row">
                  <a
                    href={l.url ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="listing-link"
                  >
                    <strong className="listing-title">{l.title ?? "Untitled listing"}</strong>
                    <span className="listing-meta muted small">
                      {formatMoney(l.price)} · {l.source}
                      {l.condition ? ` · ${l.condition}` : ""}
                    </span>
                  </a>
                  <DealChip deal={deal} />
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* T7 wires the WatchCardSheet. Opens the sheet preselected to this card
          and variant. The affordance is always enabled now — the sheet is the
          honest surface for choosing an alert type. */}
      <button
        className="primary watch-card-btn"
        onClick={() => onWatchCard?.({ cardId, variant })}
        disabled={!onWatchCard}
        title={onWatchCard ? "Set up a watch" : "Watchlist setup coming soon"}
      >
        Watch this card
      </button>

      {/* Row 21 — add this card to the shareable binder. Self-contained: POSTs
          /binder/items and surfaces honest inline status (added / already in /
          not found / verbatim error). Distinct verb-phrase from every nav tab. */}
      <AddToBinderButton cardId={cardId} variant={variant} />

      {/* Row 24 — add this card to the want list / hunt list. Self-contained:
          POSTs /wants/items and surfaces honest inline status (added / already
          on / not found / verbatim error). Distinct verb-phrase ("Hunt this
          card") from every nav tab and from "Add to binder". */}
      <AddToWantsButton cardId={cardId} variant={variant} />
    </section>
  );
}

// Compact deal-score chip attached to an active listing when the deals API
// assessed it. `🟢 RIP $<edge>` for a rip, `🟡 FLIP $<flip_to_10>` for a flip;
// a muted "not a deal" when it was assessed and neither flag is true. When no
// assessment matched (deal is undefined) the row shows no chip — honest
// absence, never a fabricated score. Never $0: formatMoney renders an em dash
// for a null edge.
function DealChip({ deal }: { deal: DealAssessment | undefined }) {
  if (!deal) return null;
  if (deal.is_rip) {
    return <span className="deal-chip rip">🟢 RIP {formatMoney(deal.rip_edge)}</span>;
  }
  if (deal.is_flip) {
    return (
      <span className="deal-chip flip">🟡 FLIP {formatMoney(deal.flip_edge_to_10)}</span>
    );
  }
  return <span className="muted small">not a deal</span>;
}