// ProofOfSales — the project's honest differentiator (roadmap row 16): every market
// price is accompanied by *proven sales* — actual eBay transactions (date, price,
// condition, title, link) — so the user sees real people paid real money, not a
// retailer's listed estimate. "99% of price apps assert a number and never prove
// anyone paid it." We prove it, or we honestly say we can't.
//
// Reusable + presentation-only: callers pass a `fetcher` returning the shared
// {sold_comps, sold_comps_unavailable, sold_comps_empty} shape, so the same block
// serves card-keyed scans (getSoldComps) and sealed-query surfaces
// (getSealedSoldComps). Honest empty flags mirror the established pattern:
//   - sold_comps_unavailable: no listings_api key -> "set a listings source key"
//   - sold_comps_empty:       key set but 0 confirmed sales -> "no recent proven sales"
// Never a fabricated $0. Links open in a new tab with rel="noopener noreferrer".
// `.proof-*` classes are additive (do-not-break); styling mirrors `.sold-comps-*`.
import { useEffect, useState } from "react";

import { formatMoney } from "../lib/format";
import { relativeTime } from "../lib/time";

export interface ProofComp {
  listing_id: string;
  price: number;
  title: string | null;
  currency: string | null;
  url: string | null;
  condition: string | null;
  sold_at: string | null;
  source: string;
}

export interface ProofOfSalesData {
  sold_comps: ProofComp[];
  sold_comps_unavailable: boolean;
  sold_comps_empty: boolean;
}

export default function ProofOfSales({
  fetcher,
  heading = "Proven sales",
  caption = "Market price is a listed estimate; these are actual eBay sales.",
}: {
  fetcher: () => Promise<ProofOfSalesData>;
  heading?: string;
  caption?: string;
}) {
  const [data, setData] = useState<ProofOfSalesData | null>(null);

  useEffect(() => {
    let alive = true;
    fetcher()
      .then((d) => { if (alive) setData(d); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [fetcher]);

  if (data === null) return <p className="proof-of-sales loading">Checking proven sales…</p>;

  if (data.sold_comps_unavailable) {
    return (
      <p className="proof-of-sales unavailable">
        Proven sales unavailable — set a listings source key to show eBay sale evidence.
      </p>
    );
  }
  if (data.sold_comps_empty || data.sold_comps.length === 0) {
    return <p className="proof-of-sales empty">No recent proven sales found on eBay.</p>;
  }

  return (
    <section className="proof-of-sales">
      <h4>{heading}</h4>
      <p className="caption">{caption}</p>
      <ul>
        {data.sold_comps.map((c) => (
          <li key={c.listing_id} className="proof-row">
            <a href={c.url ?? "#"} target="_blank" rel="noopener noreferrer" className="proof-link">
              <span className="proof-price">{formatMoney(c.price)}</span>
              {c.condition ? <span className="proof-cond">{c.condition}</span> : null}
              {c.title ? <span className="proof-title">{c.title}</span> : null}
              {c.sold_at ? <span className="proof-when">{relativeTime(c.sold_at)}</span> : null}
              <span className="proof-source">{c.source}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}