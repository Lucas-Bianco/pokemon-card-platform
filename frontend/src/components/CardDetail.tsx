import { useCallback, useEffect, useState } from "react";

import { getCard, getPriceHistory, refreshListings } from "../api/client";
import type { CardSearchResult, Listing, PricePoint } from "../api/types";
import { formatMoney } from "../lib/format";
import GradingUpside from "./GradingUpside";
import PriceChart from "./PriceChart";
import PriceLine from "./PriceLine";

interface Props {
  cardId: string;
  variant?: string;
  onBack: () => void;
}

// Loading + error + retry for the card fetch — the gating load. GradingUpside
// and PriceLine fetch their own data (reused, not duplicated), so CardDetail
// only owns the card body, the price history, and the listings.
export default function CardDetail({ cardId, variant = "normal", onBack }: Props) {
  const [card, setCard] = useState<CardSearchResult | null>(null);
  const [cardError, setCardError] = useState(false);
  const [loading, setLoading] = useState(true);

  const [history, setHistory] = useState<PricePoint[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [listings, setListings] = useState<Listing[]>([]);
  const [listingsUnavailable, setListingsUnavailable] = useState(false);
  const [listingsLoading, setListingsLoading] = useState(true);
  const [listingsError, setListingsError] = useState<string | null>(null);

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
        <PriceLine cardId={cardId} variant={variant} initial={null} />
      </div>

      {/* Reused — not duplicated. The spread panel fetches its own data. */}
      <GradingUpside cardId={cardId} variant={variant} />

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
            {listings.map((l) => (
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
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* T7 wires the WatchCardSheet. Disabled here so the affordance is visible
          without inventing a watch that does nothing. */}
      <button className="primary watch-card-btn" disabled title="Watchlist setup coming soon">
        Watch this card
      </button>
    </section>
  );
}