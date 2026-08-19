import { useState } from "react";

import { getSealedDeals } from "../api/client";
import type { SealedDealAssessment, SealedDealsResponse } from "../api/types";
import { formatMoney } from "../lib/format";
import { relativeTime } from "../lib/time";

// The Sealed-deals screen: a search box (free-text query → getSealedDeals) +
// a ranked flip-edge feed. Sealed products (booster boxes, ETBs, collection
// boxes, packs) are query-keyed, not card-keyed — the query IS the keyword.
// Every price shows its source + a relative "updated <relative>" staleness;
// every missing edge renders an em dash via formatMoney, never $0.00. The footer
// caveat rides every card — keyword listings carry seller-mislabel noise, so
// edges are indicative leads (investigate before buying).
export default function SealedDeals() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<SealedDealsResponse | null>(null);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (q.length < 2) {
      setError("Enter a sealed product to search (e.g. 'scarlet violet booster box').");
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    try {
      setData(await getSealedDeals(q));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load sealed deals.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="sealed-deals">
      <p className="muted small">
        Search a sealed product (booster box, ETB, collection box, pack) to find
        active eBay listings priced below the recent sold-comp median.
      </p>
      <form className="sealed-deals-toolbar" onSubmit={run}>
        <input
          type="search"
          className="sealed-deals-search"
          placeholder="Sealed product, e.g. 'scarlet violet booster box'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search a sealed product"
          autoComplete="off"
        />
        <button type="submit" className="sealed-deals-btn" disabled={loading}>
          {loading ? "Searching…" : "Find deals"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {loading && <div className="skeleton skeleton-block" aria-label="Loading sealed deals" />}

      {data && <SealedDealsBody data={data} />}
    </section>
  );
}

function SealedDealsBody({ data }: { data: SealedDealsResponse }) {
  // HONEST empty states — the FEATURE, not an afterthought. A missing key and
  // a queried-but-empty source carry different honest copy; a null market
  // (no sold comps) surfaces "no market price" rather than a fabricated $0.
  if (data.listings_unavailable) {
    return (
      <p className="muted">
        Set CARDPLATFORM_LISTINGS_API_KEY (your eBay App ID) to search sealed listings.
      </p>
    );
  }
  if (data.listings_empty) {
    return (
      <p className="muted">
        No active listings found for “{data.query}”. Try a broader query.
      </p>
    );
  }
  if (data.deals.length === 0) {
    return <p className="muted">No deals right now for “{data.query}”.</p>;
  }

  return (
    <>
      <div className="sealed-deals-market">
        <span className="sealed-deals-market-label">Sealed market (median sold)</span>{" "}
        {data.sealed_market ? (
          <span className="sealed-deals-market-value">
            {formatMoney(data.sealed_market.price)}
            <span className="muted small">
              {" "}
              {data.sealed_market.source}
              {data.sealed_market.source_updated_at
                ? ` · updated ${relativeTime(data.sealed_market.source_updated_at)}`
                : ""}
            </span>
          </span>
        ) : (
          <span className="muted small">— no market price</span>
        )}
      </div>
      {data.sealed_market === null && (
        <p className="muted small">
          No recent sold comps to establish a market price — flip edges unavailable.
        </p>
      )}
      <ul className="sealed-deal-list">
        {data.deals.map((d) => (
          <SealedDealCard key={d.listing_id} deal={d} />
        ))}
      </ul>
      <p className="sealed-deal-caveat muted small">
        Edges are gross of selling fees. Investigate before buying — keyword listings carry
        seller-mislabel noise.
      </p>
    </>
  );
}

function SealedDealCard({ deal }: { deal: SealedDealAssessment }) {
  const isAuction = deal.listing_type === "auction" && deal.auction_end_at;

  return (
    <li className={`sealed-deal${deal.is_flip ? " sealed-deal--flip" : ""}`}>
      <div className="sealed-deal-head">
        <a
          className="sealed-deal-title"
          href={deal.url ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
        >
          <strong>{deal.title ?? "Untitled listing"}</strong>
        </a>
        <span className="sealed-deal-price">{formatMoney(deal.listing_price)}</span>
      </div>
      <div className="sealed-deal-meta muted small">
        {deal.condition ?? "Condition unknown"}
        {isAuction ? " · auction" : ""}
      </div>

      {/* Flip row — sealed market vs listing. Em dash + "no market price" when
          there are no sold comps; the edge is null right alongside it, never a
          fabricated $0.00. */}
      <div className="sealed-deal-row sealed-deal-flip">
        <span className="sealed-deal-row-label">Flip edge</span>
        <span className="sealed-deal-row-value">{formatMoney(deal.flip_edge)}</span>
      </div>

      {/* Deal chips — only the flag that is true. Never an inflated chip. */}
      <div className="sealed-deal-chips">
        {deal.is_flip && <span className="sealed-deal__chip">💰 FLIP</span>}
        {!deal.is_flip && <span className="muted small">not a deal at this price</span>}
      </div>
    </li>
  );
}