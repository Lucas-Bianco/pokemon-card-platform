import { useCallback, useEffect, useRef, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import { getDeals, getDealsFeed, searchCards } from "../api/client";
import type { CardSearchResult, DealAssessment, DealsResponse } from "../api/types";
import { formatMoney } from "../lib/format";
import { relativeTime } from "../lib/time";
import { staggerContainer, staggerItem } from "./motion";

interface Props {
  onOpenCard?: (card: { cardId: string; variant?: string }) => void;
}

// Auction countdown — distinct from relativeTime (which describes elapsed
// past time). Frames the same magnitudes as "ends in 3m" / "ended 3m ago" so a
// future auction end reads as a countdown and a past one reads honestly as
// over. Returns "" for an unparseable date. Kept local: no existing auction
// helper in the codebase to reuse.
function auctionCountdown(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = then - Date.now();
  const past = diff < 0;
  const abs = Math.abs(diff);
  const m = Math.floor(abs / 60_000);
  let mag: string;
  if (m < 1) mag = "<1m";
  else if (m < 60) mag = `${m}m`;
  else if (m < 60 * 24) mag = `${Math.floor(m / 60)}h`;
  else mag = `${Math.floor(m / 60 / 24)}d`;
  return past ? `ended ${mag} ago` : `ends in ${mag}`;
}

// The Deals screen: a search box (debounced → existing searchCards) + a
// "Watched cards" toggle (default ON). With the toggle ON and no card picked,
// the cross-card feed (getDealsFeed) defaults to the user's active watched
// cards on the backend. Picking a card from search loads that card's deals
// (getDeals). Every price shows its source + a relative "updated <relative>"
// staleness; every missing edge renders an em dash, never $0. The footer
// caveat rides every card — keyword listings carry seller-mislabel noise.
export default function Deals({ onOpenCard }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CardSearchResult[]>([]);
  const [pickedCard, setPickedCard] = useState<CardSearchResult | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [watchedOnly, setWatchedOnly] = useState(true);

  const [data, setData] = useState<DealsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounced card search — mirrors Browse/WatchCardSheet: 300ms, never sends
  // an empty query (the backend requires min_length=1).
  useEffect(() => {
    const q = query.trim();
    if (q === "") {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearchBusy(true);
    const t = setTimeout(() => {
      searchCards(q)
        .then((rs) => {
          if (!cancelled) setResults(rs);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearchBusy(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query]);

  // Load: a picked card → its deals; else when the watched toggle is ON → the
  // cross-card feed (defaults to watched cards on the backend); else nothing
  // (the user turned the toggle off without picking a card). A monotonically
  // increasing token guards against a stale response overwriting a newer one
  // if the user picks a card while a feed fetch is in flight.
  const reqToken = useRef(0);
  const load = useCallback(async () => {
    const token = ++reqToken.current;
    setLoading(true);
    setError(null);
    try {
      let res: DealsResponse;
      if (pickedCard) {
        res = await getDeals(pickedCard.id);
      } else if (watchedOnly) {
        res = await getDealsFeed();
      } else {
        setData(null);
        setLoading(false);
        return;
      }
      if (token !== reqToken.current) return;
      setData(res);
    } catch (err) {
      if (token !== reqToken.current) return;
      setError(err instanceof Error ? err.message : "Couldn't load deals.");
    } finally {
      if (token === reqToken.current) setLoading(false);
    }
  }, [pickedCard, watchedOnly]);

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

  function pickCard(card: CardSearchResult) {
    setPickedCard(card);
    setQuery("");
    setResults([]);
  }

  function clearPicked() {
    setPickedCard(null);
  }

  return (
    <section className="deals">
      <div className="deals-toolbar">
        <input
          type="search"
          className="deals-search"
          placeholder="Search a card to find deals"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search a card to find deals"
          autoComplete="off"
        />
        <label className="deals-toggle">
          <input
            type="checkbox"
            checked={watchedOnly}
            onChange={(e) => setWatchedOnly(e.target.checked)}
          />
          <span>Watched cards</span>
        </label>
      </div>

      {pickedCard && (
        <div className="deals-picked">
          <strong>{pickedCard.name}</strong>
          <span className="muted small">
            {pickedCard.set_name} · #{pickedCard.number}
          </span>
          <button className="link" onClick={clearPicked}>
            Clear
          </button>
        </div>
      )}

      {searchBusy && <p className="muted small">Searching…</p>}
      {!searchBusy && query.trim() !== "" && results.length === 0 && (
        <p className="muted small">No cards found.</p>
      )}
      {results.length > 0 && (
        <ul className="deals-search-results">
          {results.slice(0, 8).map((r) => (
            <li key={r.id}>
              <button className="deals-search-row" onClick={() => pickCard(r)}>
                <strong>{r.name}</strong>
                <span className="muted small">
                  {r.set_name} · #{r.number}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <DealsBody
        loading={loading}
        error={error}
        data={data}
        onRetry={() => void load()}
        onOpenCard={onOpenCard}
      />
    </section>
  );
}

function DealsBody({
  loading,
  error,
  data,
  onRetry,
  onOpenCard,
}: {
  loading: boolean;
  error: string | null;
  data: DealsResponse | null;
  onRetry: () => void;
  onOpenCard?: (card: { cardId: string; variant?: string }) => void;
}) {
  const reduced = useReducedMotion();
  // "Show only deals" — collapses the feed to just the RIP/FLIP cards, the
  // thing a sniper scanning the ranked list wants to act on. Default off so
  // the full ranked feed (with its "not a deal" context cards) still renders.
  // Hooks must run before the early returns below.
  const [dealsOnly, setDealsOnly] = useState(false);
  useEffect(() => {
    setDealsOnly(false);
  }, [data]);
  if (loading) {
    return <div className="skeleton skeleton-block" aria-label="Loading deals" />;
  }
  if (error) {
    return (
      <div className="deals-error">
        <p className="error">{error}</p>
        <button className="link" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (!data) {
    // Toggle OFF and no card picked — an honest prompt, not a fabricated feed.
    return <p className="muted small">Search a card to find deals, or turn on Watched cards.</p>;
  }

  // HONEST empty states — the FEATURE, not an afterthought. Never an empty list
  // dressed as "no deals right now": a missing key and a queried-but-empty
  // source carry different honest copy.
  if (data.listings_unavailable) {
    return <p className="muted">Set a listings source key (eBay) to find deals.</p>;
  }
  if (data.listings_empty) {
    return <p className="muted">No active listings for this card right now.</p>;
  }
  if (data.deals.length === 0) {
    return <p className="muted">No deals right now for this card.</p>;
  }

  const dealsCount = data.deals.filter((d) => d.is_rip || d.is_flip).length;
  const shown = dealsOnly ? data.deals.filter((d) => d.is_rip || d.is_flip) : data.deals;

  return (
    <>
      {/* At-a-glance feed summary + a "Show only deals" focus filter. Honest
          counts only (never a summed $); the filter is hidden when nothing is
          a deal, so you never see a toggle that empties the list. */}
      <div className="deals-summary muted small">
        {data.deals.length} listing{data.deals.length === 1 ? "" : "s"} · {dealsCount} deal
        {dealsCount === 1 ? "" : "s"}
        {dealsCount > 0 && (
          <label className="deals-filter">
            <input
              type="checkbox"
              checked={dealsOnly}
              onChange={(e) => setDealsOnly(e.target.checked)}
            />
            <span>Show only deals</span>
          </label>
        )}
      </div>

      <motion.ul
        className="deal-list"
        variants={staggerContainer}
        initial={reduced ? "show" : "hidden"}
        animate="show"
      >
        {shown.map((d) => (
          <DealCard
            key={d.listing_id}
            deal={d}
            cardId={data.card_id}
            variant={data.variant}
            onOpenCard={onOpenCard}
          />
        ))}
      </motion.ul>
    </>
  );
}

function DealCard({
  deal,
  cardId,
  variant,
  onOpenCard,
}: {
  deal: DealAssessment;
  cardId: string | null;
  variant: string | null;
  onOpenCard?: (card: { cardId: string; variant?: string }) => void;
}) {
  const reduced = useReducedMotion();
  const isAuction = deal.listing_type === "auction" && deal.auction_end_at;
  const countdown = auctionCountdown(deal.auction_end_at);

  // The DealAssessment has no per-listing `source` field — only the comp/market
  // sources carry an honest provenance. Render those where their prices show,
  // and never fabricate an "eBay" badge for the listing row itself.
  return (
    <motion.li
      className="deal-card"
      variants={staggerItem}
      whileHover={reduced ? undefined : { y: -4 }}
      whileTap={reduced ? undefined : { scale: 0.985 }}
      transition={{ duration: 0.16 }}
    >
      <div className="deal-card-head">
        <a
          className="deal-title"
          href={deal.url ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
        >
          <strong>{deal.title ?? "Untitled listing"}</strong>
        </a>
        <span className="deal-price">{formatMoney(deal.listing_price)}</span>
      </div>
      <div className="deal-card-meta muted small">
        {deal.condition ?? "Condition unknown"}
        {isAuction ? ` · auction · ${countdown}` : ""}
        {/* "view" opens the CARD, so it needs a real card id. A DealAssessment
            carries only the marketplace `listing_id` — passing that to
            CardDetail resolves nothing. The card id lives on the RESPONSE:
            set for the per-card route, null for the cross-card feed (which
            merges deals across cards and cannot attribute a row). No id → no
            link, rather than a link that always dead-ends. */}
        {onOpenCard && cardId ? (
          <>
            {" · "}
            <button
              className="link"
              onClick={() => onOpenCard({ cardId, variant: variant ?? undefined })}
            >
              view
            </button>
          </>
        ) : null}
      </div>

      {/* Rip row — raw market vs listing. Em dash + "no market price" when
          there is no market snapshot; flip edges may still compute. */}
      <div className="deal-row deal-rip">
        <span className="deal-row-label">Raw market</span>
        {deal.raw_market ? (
          <span className="deal-row-value">
            {formatMoney(deal.raw_market.price)}
            <span className="muted small">
              {" "}
              {deal.raw_market.source} · updated {relativeTime(deal.raw_market.source_updated_at)}
            </span>
          </span>
        ) : (
          <span className="deal-row-value muted small">— no market price</span>
        )}
        <span className="deal-row-edge">
          <span className="muted small">Rip edge</span>{" "}
          <span className="deal-rip-edge">{formatMoney(deal.rip_edge)}</span>
          {deal.is_rip && <span className="muted small"> below market</span>}
        </span>
      </div>

      {/* Flip row — graded comps vs listing, net of the grading fee. Em dash
          for any missing comp/edge; never a fabricated spread. */}
      <div className="deal-row deal-flip">
        <span className="deal-row-label">PSA 10 comp</span>
        <span className="deal-row-value">
          {deal.psa10_comp ? (
            <>
              {formatMoney(deal.psa10_comp.price)}
              <span className="muted small">
                {" "}
                {deal.psa10_comp.source} · updated{" "}
                {relativeTime(deal.psa10_comp.source_updated_at)}
              </span>
            </>
          ) : (
            <span className="muted small">—</span>
          )}
        </span>
        <span className="deal-row-edges">
          <span className="muted small">Flip to 10</span>{" "}
          <span className="deal-flip-10">{formatMoney(deal.flip_edge_to_10)}</span>
          <span className="muted small"> · Flip to 9</span>{" "}
          <span className="deal-flip-9">{formatMoney(deal.flip_edge_to_9)}</span>
          <span className="muted small">
            {" "}
            after {formatMoney(deal.grading_fee)} grading fee
          </span>
        </span>
      </div>

      {/* Deal chips — only the flags that are true. Never an inflated chip. */}
      <div className="deal-chips">
        {deal.is_rip && <span className="deal-chip rip">🟢 RIP</span>}
        {deal.is_flip && <span className="deal-chip flip">🟡 FLIP</span>}
        {!deal.is_rip && !deal.is_flip && (
          <span className="muted small">not a deal at this price</span>
        )}
      </div>

      {/* Footer caveat — rides every card; keyword listings carry noise. */}
      <p className="deal-caveat muted small">
        Investigate before buying — keyword listings carry seller-mislabel noise.
      </p>
    </motion.li>
  );
}