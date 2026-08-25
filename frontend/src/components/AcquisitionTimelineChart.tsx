// Collection growth over time — cumulative card count + cumulative cost basis at
// each distinct holding acquired_at, oldest-first. The acquisition-driven
// counterpart to the price-driven value-over-time chart (row 25): this is when
// you *built* the collection, not what it was worth. The card line is always
// populated (acquired_at defaults to now on add); the cost line sums only
// holdings with a recorded purchase price — unpriced acquisitions raise the card
// line only, never a fabricated $0 cost line. Undated holdings are excluded from
// the timeline, counted separately, never a point at time zero.
import { useEffect, useState } from "react";

import { getAcquisitionTimeline } from "../api/client";
import type { AcquisitionPoint, AcquisitionTimeline as AcquisitionTimelineT } from "../api/types";
import { formatMoney } from "../lib/format";

const WIDTH = 320;
const HEIGHT = 140;
const PAD = 14;

function scale(points: AcquisitionPoint[]): string[] {
  // Scale the cumulative CARDS line (always populated). One axis only — the cost
  // line is shown as a figure in the caption, not a second axis, so the chart
  // stays legible at phone width and never implies a $-y it can't honestly draw.
  const values = points.map((p) => p.cumulative_cards);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1; // avoid divide-by-zero when every point agrees
  const innerW = WIDTH - PAD * 2;
  const innerH = HEIGHT - PAD * 2;
  const step = points.length > 1 ? innerW / (points.length - 1) : 0;
  return points.map((p, i) => {
    const x = PAD + i * step;
    const y = HEIGHT - PAD - ((p.cumulative_cards - min) / span) * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

export default function AcquisitionTimelineChart() {
  const [data, setData] = useState<AcquisitionTimelineT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    getAcquisitionTimeline()
      .then((t) => {
        if (alive) setData(t);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Could not load acquisition timeline.");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="error small">{error}</p>;
  if (data === null) {
    return <div className="skeleton skeleton-block" aria-label="Loading acquisition timeline" />;
  }

  // Defensive: a 200 with the wrong shape degrades to the honest empty state
  // rather than throwing on `points.length`. Never fabricated.
  const points = data.points ?? [];

  // No holdings, or every holding undated (no acquired_at to plot against).
  // Either way: honest empty, never a point at 0 / time zero.
  if (points.length === 0) {
    return (
      <section className="acquisition-timeline" aria-label="Collection growth over time">
        <h3>Collection growth</h3>
        <p className="muted small">
          {data.total_holdings === 0
            ? "No holdings yet — scan a card to start building your portfolio."
            : `${data.undated_holdings} holding${data.undated_holdings === 1 ? "" : "s"} with no acquired date, so there is no growth timeline to draw. Undated holdings are counted, never a point at time zero.`}
        </p>
        <p className="acquisition-timeline-caveat muted small">{data.caveat}</p>
      </section>
    );
  }

  // One observation can't show a trend; one dot plus an honest note, never a line.
  if (points.length === 1) {
    const only = points[0];
    return (
      <section className="acquisition-timeline" aria-label="Collection growth over time">
        <h3>Collection growth</h3>
        <div className="price-chart">
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Collection growth timeline">
            <circle cx={WIDTH / 2} cy={HEIGHT / 2} r={4} className="chart-dot" />
          </svg>
          <p className="chart-note muted small">
            One acquisition ({only.cumulative_cards} card{only.cumulative_cards === 1 ? "" : "s"} on {fmtDate(only.observed_at)}) — need more history to draw a trend.
          </p>
        </div>
        <p className="acquisition-timeline-caveat muted small">{data.caveat}</p>
      </section>
    );
  }

  const cards = points.map((p) => p.cumulative_cards);
  const minCards = Math.min(...cards);
  const maxCards = Math.max(...cards);
  const currentCards = cards[cards.length - 1];
  const currentCost = points[points.length - 1].cumulative_cost_basis;
  const coords = scale(points);

  return (
    <section className="acquisition-timeline" aria-label="Collection growth over time">
      <h3>Collection growth</h3>
      <div className="price-chart">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Collection growth timeline">
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
          <span className="low">min {minCards}</span>
          <span className="high">max {maxCards}</span>
          <span className="current">{currentCards} cards</span>
        </p>
        <p className="chart-caption muted small">
          {points.length} acquisition{points.length === 1 ? "" : "s"} · cost basis {formatMoney(currentCost)}
          {data.holdings_without_cost > 0
            ? ` (known for ${data.holdings_with_cost} of ${data.holdings_with_cost + data.holdings_without_cost} holdings, never $0)`
            : ""}
          {data.undated_holdings > 0 ? ` · ${data.undated_holdings} undated (excluded)` : ""}
        </p>
      </div>
      <p className="acquisition-timeline-caveat muted small">{data.caveat}</p>
    </section>
  );
}