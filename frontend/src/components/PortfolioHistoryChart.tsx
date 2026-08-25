// Portfolio value over time — the reconstructed total market value of your
// *current* holdings at each past price observation, from append-only snapshots.
// Mirrors the per-card PriceChart's inline-SVG approach and honest-depth ethos.
// Honest: points are computed server-side using the same TCGplayer-then-Cardmarket
// resolution the rest of the app uses; unpriced holdings are excluded (never $0);
// no points means no history yet, not a flat zero line. The reconstruction holds
// your current holdings fixed — cards you've since sold or added aren't in past
// totals — and that caveat is shown verbatim from the server.
import { useEffect, useState } from "react";

import { getPortfolioHistory } from "../api/client";
import type { PortfolioHistory, PortfolioValuePoint } from "../api/types";
import { formatMoney } from "../lib/format";

const WIDTH = 320;
const HEIGHT = 140;
const PAD = 14;

function scale(points: PortfolioValuePoint[]): string[] {
  const values = points.map((p) => p.market_value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1; // avoid divide-by-zero when every observation agrees
  const innerW = WIDTH - PAD * 2;
  const innerH = HEIGHT - PAD * 2;
  const step = points.length > 1 ? innerW / (points.length - 1) : 0;
  return points.map((p, i) => {
    const x = PAD + i * step;
    const y = HEIGHT - PAD - ((p.market_value - min) / span) * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
}

function fmtDate(iso: string): string {
  // ISO observed_at -> a short, locale-agnostic date label. Never implies more
  // precision than the snapshot actually has.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

export default function PortfolioHistoryChart() {
  const [data, setData] = useState<PortfolioHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    getPortfolioHistory()
      .then((h) => {
        if (alive) setData(h);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Could not load portfolio history.");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="error small">{error}</p>;
  if (data === null) {
    return <div className="skeleton skeleton-block" aria-label="Loading portfolio history" />;
  }

  // Defensive: a 200 with the wrong shape (e.g. a misrouted proxy) degrades to the
  // honest empty state rather than throwing on `points.length`. Never fabricated.
  const points = data.points ?? [];

  // No holdings, or holdings but no price snapshots yet. Either way: honest empty,
  // never a point at $0.
  if (points.length === 0) {
    return (
      <section className="portfolio-history" aria-label="Portfolio value over time">
        <h3>Portfolio value over time</h3>
        <p className="muted small">
          {data.total_items === 0
            ? "No holdings yet — scan a card to start building your portfolio."
            : "No price history yet. Your holdings have not been observed by a price refresh, so there is no timeline to draw."}
        </p>
        <p className="portfolio-history-caveat muted small">{data.caveat}</p>
      </section>
    );
  }

  // One observation can't show a trend; one dot plus an honest note, never a line.
  if (points.length === 1) {
    const only = points[0];
    return (
      <section className="portfolio-history" aria-label="Portfolio value over time">
        <h3>Portfolio value over time</h3>
        <div className="price-chart">
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Portfolio value history">
            <circle cx={WIDTH / 2} cy={HEIGHT / 2} r={4} className="chart-dot" />
          </svg>
          <p className="chart-note muted small">
            One observation ({formatMoney(only.market_value)} across {only.priced_items} priced holding
            {only.priced_items === 1 ? "" : "s"}) — need more history to draw a trend.
          </p>
          <p className="chart-caption muted small">as of {fmtDate(only.observed_at)}</p>
        </div>
        <p className="portfolio-history-caveat muted small">{data.caveat}</p>
      </section>
    );
  }

  const values = points.map((p) => p.market_value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const current = values[values.length - 1];
  const latest = points[points.length - 1];
  const coords = scale(points);

  return (
    <section className="portfolio-history" aria-label="Portfolio value over time">
      <h3>Portfolio value over time</h3>
      <div className="price-chart">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Portfolio value history">
          <polyline points={coords.join(" ")} className="chart-line" fill="none" />
          {coords.map((coord, i) => (
            <circle
              key={`${points[i].observed_at}-${i}`}
              cx={Number(coord.split(",")[0])}
              cy={Number(coord.split(",")[1])}
              r={2.5}
              className="chart-point"
            />
          ))}
        </svg>
        <p className="chart-labels">
          <span className="low">min {formatMoney(min)}</span>
          <span className="high">max {formatMoney(max)}</span>
          <span className="current">current {formatMoney(current)}</span>
        </p>
        <p className="chart-caption muted small">
          {latest.priced_items} priced holding{latest.priced_items === 1 ? "" : "s"}
          {latest.unpriced_items > 0 ? ` · ${latest.unpriced_items} unpriced (excluded, never $0)` : ""} · as
          of {fmtDate(latest.observed_at)}
        </p>
        <p className="chart-depth muted small">
          {points.length} point{points.length === 1 ? "" : "s"} · depth depends on price-refresh cadence
          (snapshots are append-only, never trimmed).
        </p>
      </div>
      <p className="portfolio-history-caveat muted small">{data.caveat}</p>
    </section>
  );
}