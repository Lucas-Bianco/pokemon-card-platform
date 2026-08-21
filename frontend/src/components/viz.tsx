// Inline-SVG data viz for the Dashboard. No chart lib — pure SVG so it scales
// to any viewport and stays crisp. Honest-empty: a Donut with no allocation
// renders a single muted ring + a "—" center; MoverBars with no movers renders
// an honest empty note, never fabricated bars.
import type { Allocation, PortfolioItem } from "../api/types";

function formatMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

// A donut of portfolio allocation by set. `allocation` is summary.allocation:
// each entry has set_name + market_value. Slices are proportional to market_value;
// the center shows the total. Honest-empty when total <= 0 or no allocation.
export function Donut({ allocation, total, size = 180 }: { allocation: Allocation[]; total: number; size?: number }) {
  const slices = (allocation ?? []).filter((a) => a.market_value > 0);
  const ring = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * ring;
  const valid = total > 0 && slices.length > 0;

  const COLORS = ["#ffcb05", "#3b6df0", "#ee6b2e", "#7ac74c", "#c063e0", "#5bc7d0", "#e0587c", "#9aa4b2"];

  if (!valid) {
    return (
      <svg className="donut" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Allocation by set: no holdings">
        <circle cx={cx} cy={cy} r={ring} fill="none" stroke="var(--line)" strokeWidth={12} opacity={0.6} />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" className="donut-center">—</text>
      </svg>
    );
  }

  let offset = 0;
  return (
    <svg className="donut" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Allocation by set, total ${formatMoney(total)}`}>
      <circle cx={cx} cy={cy} r={ring} fill="none" stroke="var(--line)" strokeWidth={12} opacity={0.35} />
      {slices.map((a, i) => {
        const frac = a.market_value / total;
        const len = frac * circ;
        const dash = `${len} ${circ - len}`;
        const el = (
          <circle
            key={a.set_id ?? i}
            cx={cx}
            cy={cy}
            r={ring}
            fill="none"
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={12}
            strokeDasharray={dash}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${cx} ${cy})`}
            strokeLinecap="butt"
          />
        );
        offset += len;
        return el;
      })}
      <text x={cx} y={cy - 6} textAnchor="middle" dominantBaseline="central" className="donut-center donut-total">{formatMoney(total)}</text>
      <text x={cx} y={cy + 14} textAnchor="middle" dominantBaseline="central" className="donut-center donut-sub">total value</text>
    </svg>
  );
}

// Horizontal bars for top gainers / losers. Each row: name, a signed bar, and the
// unrealized amount. Honest-empty when the list is empty.
export function MoverBars({ items, kind }: { items: PortfolioItem[]; kind: "gainers" | "losers" }) {
  const rows = (items ?? []).slice(0, 5);
  if (rows.length === 0) {
    return <p className="muted small movers-empty">{kind === "gainers" ? "No gainers yet." : "No losers yet."}</p>;
  }
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.unrealized ?? 0)));
  const color = kind === "gainers" ? "var(--ok)" : "var(--down)";
  return (
    <ul className={`movers movers-${kind}`}>
      {rows.map((r) => {
        const u = r.unrealized ?? 0;
        const pct = Math.min(100, (Math.abs(u) / max) * 100);
        return (
          <li key={r.id} className="mover-row">
            <span className="mover-name" title={r.card_name}>{r.card_name}</span>
            <span className="mover-track" aria-hidden="true">
              <span className="mover-bar" style={{ width: `${pct}%`, background: color }} />
            </span>
            <span className={`mover-amt ${u >= 0 ? "up" : "down"}`}>{formatMoney(u)}</span>
          </li>
        );
      })}
    </ul>
  );
}