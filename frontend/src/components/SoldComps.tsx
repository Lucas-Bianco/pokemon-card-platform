// "Recent sold (eBay)" evidence block — sold comps backing the raw market
// price. Sold comps are NOT a price target; they're evidence ("market $120
// because these 3 just sold at $118/$121/$119"). Honest empty states: no key
// -> unavailable hint; key set but no comps -> "no recent sold comps". Never a
// fabricated $0. formatMoney takes a single value arg (no currency).
import { useEffect, useState } from "react";

import { getSoldComps } from "../api/client";
import type { SoldCompsResponse } from "../api/types";
import { relativeTime } from "../lib/time";
import { formatMoney } from "../lib/format";

export default function SoldComps({ cardId, variant }: { cardId: string; variant: string }) {
  const [data, setData] = useState<SoldCompsResponse | null>(null);

  useEffect(() => {
    let alive = true;
    getSoldComps(cardId, variant, 3)
      .then((d) => { if (alive) setData(d); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [cardId, variant]);

  if (data === null) return <p className="sold-comps loading">Checking recent sales…</p>;

  if (data.sold_comps_unavailable) {
    return (
      <p className="sold-comps unavailable">
        Recent sold comps unavailable — set a listings source key to show eBay sale evidence.
      </p>
    );
  }
  if (data.sold_comps_empty || data.sold_comps.length === 0) {
    return <p className="sold-comps empty">No recent sold comps found on eBay for this card.</p>;
  }

  return (
    <section className="sold-comps">
      <h4>Recent sold (eBay)</h4>
      <p className="sold-comps caption">
        Sold comps are evidence backing the market price, not a price target.
      </p>
      <ul>
        {data.sold_comps.map((c) => (
          <li key={c.listing_id} className="sold-comp-row">
            <a href={c.url ?? "#"} target="_blank" rel="noreferrer" className="sold-comp-link">
              <span className="sold-comp-price">{formatMoney(c.price)}</span>
              {c.condition ? <span className="sold-comp-cond">{c.condition}</span> : null}
              {c.sold_at ? (
                <span className="sold-comp-when">{relativeTime(c.sold_at)}</span>
              ) : null}
              <span className="sold-comp-source">{c.source}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}