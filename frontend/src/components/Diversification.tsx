// Portfolio concentration & diversification — where the collection's *priced*
// value is concentrated. Top holdings with share + cumulative share, concentration
// ratios (how many cards carry 50/80/90% of priced value), and value buckets by
// rarity / supertype / set. Honest: shares are against priced_total only; unpriced
// cards are counted in unpriced_items and excluded from every total and share,
// never guessed at $0. A high concentration is a risk flag, not a trade verdict.
import { useEffect, useState } from "react";

import { getDiversification } from "../api/client";
import type { BucketShare, Concentration, Diversification as DiversificationT, HoldingShare } from "../api/types";
import { formatMoney } from "../lib/format";

function pct(share: number): string {
  // Round to a whole percent for the headline/tiles; a genuine 0 is a real 0%.
  return `${Math.round(share * 100)}%`;
}

function ConcentrationTile({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="diversification-tile">
      <span className="label">{label}</span>
      <strong>{value === null ? "—" : `${value} card${value === 1 ? "" : "s"}`}</strong>
    </div>
  );
}

function BucketList({ title, buckets }: { title: string; buckets: BucketShare[] }) {
  if (buckets.length === 0) return null;
  return (
    <div className="diversification-buckets">
      <h4>{title}</h4>
      <ul>
        {buckets.map((b) => (
          <li key={b.label}>
            <div className="diversification-bucket-row">
              <span className="diversification-bucket-label">{b.label}</span>
              <span className="diversification-bucket-value">
                {formatMoney(b.market_value)}{" "}
                <span className="muted small">· {pct(b.share)} · {b.holdings} holding{b.holdings === 1 ? "" : "s"}</span>
              </span>
            </div>
            <div className="diversification-bar" aria-hidden="true">
              <div className="diversification-bar-fill" style={{ width: `${Math.round(b.share * 100)}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HoldingRow({ h }: { h: HoldingShare }) {
  return (
    <li className="diversification-holding">
      <div className="diversification-holding-name">
        <strong>{h.card_name}</strong>
        <span className="muted small">
          {" "}{h.set_name} · ×{h.quantity} · {formatMoney(h.market_value)}
        </span>
      </div>
      <div className="diversification-holding-share">
        <span className="diversification-share-text">{pct(h.share)}</span>
        <div className="diversification-bar" aria-hidden="true">
          <div className="diversification-bar-fill" style={{ width: `${Math.round(h.share * 100)}%` }} />
        </div>
        <span className="muted small diversification-cumulative">cum. {pct(h.cumulative_share)}</span>
      </div>
    </li>
  );
}

function concentrationHeadline(d: DiversificationT): string | null {
  const c: Concentration = d.concentration;
  if (d.priced_total === 0 || c.cards_for_50 === null) return null;
  // Lead with the most striking ratio available: 80% then 50%.
  if (c.cards_for_80 !== null) {
    return `Your top ${c.cards_for_80} card${c.cards_for_80 === 1 ? "" : "s"} carry 80% of your collection's priced value.`;
  }
  return `Your top ${c.cards_for_50} card${c.cards_for_50 === 1 ? "" : "s"} carry half of your collection's priced value.`;
}

export default function Diversification() {
  const [data, setData] = useState<DiversificationT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    getDiversification()
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Could not load diversification.");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="error small">{error}</p>;
  if (data === null) {
    return <div className="skeleton skeleton-block" aria-label="Loading diversification" />;
  }

  const headline = concentrationHeadline(data);
  const allUnpriced = data.priced_total === 0;

  return (
    <section className="diversification" aria-label="Portfolio concentration and diversification">
      <h3>Concentration &amp; diversification</h3>

      {allUnpriced ? (
        <p className="muted small">
          None of your {data.total_items} card{data.total_items === 1 ? "" : "s"} have a market price yet, so there is
          no priced value to concentrate. Unpriced cards are counted, never guessed at $0.
        </p>
      ) : (
        <>
          {headline && <p className="diversification-headline">{headline}</p>}
          <div className="diversification-tiles">
            <div className="diversification-tile">
              <span className="label">Largest holding</span>
              <strong>
                {data.concentration.top_share === null ? "—" : pct(data.concentration.top_share)}
              </strong>
              <span className="muted small">of priced value</span>
            </div>
            <ConcentrationTile label="50% of value" value={data.concentration.cards_for_50} />
            <ConcentrationTile label="80% of value" value={data.concentration.cards_for_80} />
            <ConcentrationTile label="90% of value" value={data.concentration.cards_for_90} />
          </div>
          <p className="muted small">
            Priced value {formatMoney(data.priced_total)} across {data.priced_items} priced holding
            {data.priced_items === 1 ? "" : "s"}
            {data.unpriced_items > 0
              ? ` · ${data.unpriced_items} unpriced (excluded from shares, never $0)`
              : ""}
            .
          </p>
        </>
      )}

      {data.top_holdings.length > 0 && (
        <div className="diversification-top">
          <h4>Top holdings by value</h4>
          <ul>
            {data.top_holdings.map((h) => (
              <HoldingRow key={`${h.card_id}-${h.variant}`} h={h} />
            ))}
          </ul>
        </div>
      )}

      <BucketList title="By rarity" buckets={data.by_rarity} />
      <BucketList title="By supertype" buckets={data.by_supertype} />
      <BucketList title="By set" buckets={data.by_set} />

      <p className="diversification-caveat muted small">{data.caveat}</p>
    </section>
  );
}