import type { PricePoint } from "../api/types";
import { formatMoney } from "../lib/format";

interface Props {
  points: PricePoint[];
  variant: string;
  onClose?: () => void;
}

// Hand-rolled inline SVG — zero chart libraries, matching the project's minimal-deps ethos.
// Layout is computed in viewBox units so jsdom (no layout engine) still renders the shape;
// tests assert on `polyline`/`circle` presence and text content, not pixel geometry.
const WIDTH = 320;
const HEIGHT = 140;
const PAD = 14;

function scale(priced: PricePoint[]): string[] {
  const values = priced.map((p) => p.market as number);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1; // avoid divide-by-zero when every snapshot agrees
  const innerW = WIDTH - PAD * 2;
  const innerH = HEIGHT - PAD * 2;
  const step = priced.length > 1 ? innerW / (priced.length - 1) : 0;
  return priced.map((p, i) => {
    const x = PAD + i * step;
    const y = HEIGHT - PAD - ((p.market as number) - min) / span * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
}

export default function PriceChart({ points, variant, onClose }: Props) {
  const priced = points.filter((p) => p.market !== null && p.market !== undefined);

  // No snapshots at all — the card has never been observed by the price refresh job.
  if (points.length === 0) {
    return (
      <div className="price-chart">
        <p className="muted">No price history yet.</p>
      </div>
    );
  }

  // Snapshots exist but none carried a market value — never drawn as a flat zero line,
  // which would falsely imply the card is worthless. Say it was observed, not valued.
  if (priced.length === 0) {
    return (
      <div className="price-chart">
        <p className="muted">Unpriced — observed but never given a market value.</p>
      </div>
    );
  }

  // A single priced point can't show a trend; one dot plus an honest note, never a line.
  if (priced.length === 1) {
    const only = priced[0];
    return (
      <div className="price-chart">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${variant} price history`}>
          <circle cx={WIDTH / 2} cy={HEIGHT / 2} r={4} className="chart-dot" />
        </svg>
        <p className="chart-note muted small">
          One price point ({formatMoney(only.market)}) — need more history to draw a trend.
        </p>
        <p className="chart-caption muted small">
          {only.source} · as of {only.source_updated_at}
        </p>
      </div>
    );
  }

  const values = priced.map((p) => p.market as number);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const current = values[values.length - 1];
  const latestPriced = priced[priced.length - 1];

  return (
    <div className="price-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${variant} price history`}>
        <polyline points={scale(priced).join(" ")} className="chart-line" fill="none" />
        {scale(priced).map((coord, i) => (
          <circle key={`${priced[i].fetched_at}-${i}`} cx={Number(coord.split(",")[0])} cy={Number(coord.split(",")[1])} r={2.5} className="chart-point" />
        ))}
      </svg>
      <p className="chart-labels">
        <span className="low">min {formatMoney(min)}</span>
        <span className="high">max {formatMoney(max)}</span>
        <span className="current">current {formatMoney(current)}</span>
      </p>
      <p className="chart-caption muted small">
        {latestPriced.source} · as of {latestPriced.source_updated_at}
      </p>
      {onClose && (
        <button type="button" className="link chart-close" onClick={onClose}>
          close
        </button>
      )}
    </div>
  );
}