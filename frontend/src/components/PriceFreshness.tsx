// Price freshness — band the vault's *priced* holdings by the age of each
// holding's latest price snapshot's fetched_at (when the app last refreshed it),
// not the provider's own data stamp. Four bands always present (fresh / aging /
// stale / outdated); unpriced holdings are counted separately and excluded from
// every band, never $0. Descriptive only — a stale collection is a prompt to
// refresh, never a verdict on value. The caveat is shown verbatim from the server.
import { useEffect, useState } from "react";

import { getPriceFreshness } from "../api/client";
import type { FreshnessBand, PriceFreshness as PriceFreshnessT } from "../api/types";
import { formatMoney } from "../lib/format";

// Human description of each band's age window, keyed by the server's label.
const BAND_DESCRIPTION: Record<string, string> = {
  fresh: "checked within the last 7 days",
  aging: "7–30 days since the last check",
  stale: "30–90 days since the last check",
  outdated: "over 90 days since the last check",
};

function pct(share: number): string {
  // Round to a whole percent; a genuine 0 is a real 0%.
  return `${Math.round(share * 100)}%`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

function BandRow({ band }: { band: FreshnessBand }) {
  const empty = band.holdings === 0;
  return (
    <li className={`freshness-band freshness-${band.label}${empty ? " is-empty" : ""}`}>
      <div className="freshness-band-head">
        <span className="freshness-band-label">
          <strong>{band.label[0].toUpperCase() + band.label.slice(1)}</strong>
          <span className="muted small"> · {BAND_DESCRIPTION[band.label] ?? band.label}</span>
        </span>
        <span className="freshness-band-value">
          {empty ? (
            <span className="muted small">no holdings</span>
          ) : (
            <>
              {formatMoney(band.market_value)}
              <span className="muted small">
                {" "}· {band.holdings} holding{band.holdings === 1 ? "" : "s"} · {pct(band.share)} of priced value
              </span>
            </>
          )}
        </span>
      </div>
      <div className="freshness-bar" aria-hidden="true">
        <div className={`freshness-bar-fill freshness-${band.label}`} style={{ width: `${Math.round(band.share * 100)}%` }} />
      </div>
    </li>
  );
}

export default function PriceFreshness() {
  const [data, setData] = useState<PriceFreshnessT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    getPriceFreshness()
      .then((f) => {
        if (alive) setData(f);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Could not load price freshness.");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="error small">{error}</p>;
  if (data === null) {
    return <div className="skeleton skeleton-block" aria-label="Loading price freshness" />;
  }

  // Defensive: a 200 with the wrong shape degrades to the honest empty state
  // rather than throwing on `bands.length`. Never fabricated.
  const bands = data.bands ?? [];
  const noHoldings = data.total_holdings === 0;
  const allUnpriced = data.total_holdings > 0 && data.priced_holdings === 0;

  return (
    <section className="price-freshness" aria-label="Price freshness overview">
      <h3>Price freshness</h3>

      {noHoldings ? (
        <p className="muted small">
          No holdings yet — scan a card to start building your portfolio.
        </p>
      ) : allUnpriced ? (
        <p className="muted small">
          None of your {data.total_holdings} holding{data.total_holdings === 1 ? "" : "s"} have a market price yet, so there
          is nothing to band by age. Unpriced holdings are counted, never guessed at $0.
        </p>
      ) : (
        <>
          <ul className="freshness-bands">
            {bands.map((b) => (
              <BandRow key={b.label} band={b} />
            ))}
          </ul>
          <p className="muted small">
            {data.priced_holdings} priced holding{data.priced_holdings === 1 ? "" : "s"}
            {data.unpriced_holdings > 0
              ? ` · ${data.unpriced_holdings} unpriced (excluded from bands, never $0)`
              : ""}{" "}
            · prices last refreshed between {fmtDate(data.oldest_fetched_at)} and {fmtDate(data.newest_fetched_at)}.
          </p>
        </>
      )}

      <p className="price-freshness-caveat muted small">{data.caveat}</p>
    </section>
  );
}