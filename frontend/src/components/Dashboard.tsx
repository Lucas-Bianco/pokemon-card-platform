// The Home landing surface. Frontend-only: it reads GET /collection/portfolio once
// on mount and renders animated KPIs (count-up), an allocation donut, and a
// movers bar viz. Honest-empty when there are no holdings or the fetch fails —
// never $0, never fabricated. Quick-action CTAs navigate to other tabs via
// onNavigate; their accessible names are DISTINCT verb-phrases (never an exact
// nav-tab name) so BulkScan's getByRole("button",{name:"Scan"}) still resolves
// to the single nav button.
import { useEffect, useState } from "react";
import { getPortfolio } from "../api/client";
import type { Portfolio, PortfolioSummary } from "../api/types";
import { useCountUp } from "../lib/useCountUp";
import { useReducedMotionSafe } from "../lib/useReducedMotionSafe";
import { Donut, MoverBars } from "./viz";
import { Reveal } from "./Reveal";

type Tab = "scan" | "vault" | "alerts" | "deals" | "prices" | "ledger" | "sealed" | "catalog" | "browse" | "more";

function formatMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function Dashboard({
  unread,
  onNavigate,
  onWatchCard,
}: {
  unread: number;
  onNavigate: (tab: Tab) => void;
  onWatchCard: () => void;
}) {
  const reduced = useReducedMotionSafe();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // try/catch: a failed/empty portfolio degrades to an honest empty state,
    // never throws to an unmounted component (the BulkScan stub returns {} here).
    getPortfolio()
      .then((p: Portfolio) => {
        if (cancelled) return;
        setSummary(p?.summary ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setSummary(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const market = summary?.market_value ?? 0;
  const cost = summary?.cost_basis ?? 0;
  const unrealized = summary?.unrealized ?? 0;
  const priced = summary?.priced_items ?? 0;
  const unpriced = summary?.unpriced_items ?? 0;
  const hasHoldings = market > 0 || cost > 0 || priced > 0;

  const marketDisp = useCountUp(market, 900, reduced);
  const costDisp = useCountUp(cost, 900, reduced);
  const unrealizedDisp = useCountUp(unrealized, 900, reduced);

  if (loading) {
    return <div className="dashboard dashboard-loading" aria-busy="true"><p className="muted">Loading your collection…</p></div>;
  }

  if (!hasHoldings) {
    return (
      <div className="dashboard dashboard-empty">
        <Reveal>
          <h2 className="dashboard-h">Your collection at a glance</h2>
          <p className="muted">No holdings yet. Scan a card to start building your portfolio.</p>
          <div className="dashboard-ctas">
            <button className="primary" onClick={() => onNavigate("scan")}>Start scanning</button>
            <button className="link" onClick={() => onNavigate("browse")}>Browse the catalog</button>
          </div>
        </Reveal>
      </div>
    );
  }

  const up = unrealized >= 0;
  return (
    <div className="dashboard">
      <Reveal>
        <h2 className="dashboard-h">Your collection at a glance</h2>
      </Reveal>

      <div className="dashboard-kpis">
        <Reveal delay={0.02}><Kpi label="Market value" value={formatMoney(marketDisp)} /></Reveal>
        <Reveal delay={0.06}><Kpi label="Cost basis" value={formatMoney(costDisp)} /></Reveal>
        <Reveal delay={0.1}>
          <Kpi label="Unrealized P/L" value={formatMoney(unrealizedDisp)} tone={up ? "up" : "down"} />
        </Reveal>
        <Reveal delay={0.14}>
          <Kpi label="Priced / unpriced" value={`${priced} / ${unpriced}`} />
        </Reveal>
      </div>

      <div className="dashboard-grid">
        <Reveal delay={0.16} className="dashboard-card dashboard-alloc">
          <h3 className="dashboard-card-h">Allocation by set</h3>
          <Donut allocation={summary?.allocation ?? []} total={market} />
          <ul className="alloc-legend">
            {(summary?.allocation ?? []).filter((a) => a.market_value > 0).slice(0, 6).map((a, i) => (
              <li key={a.set_id ?? i}>
                <span className="alloc-dot" style={{ background: ["#ffcb05","#3b6df0","#ee6b2e","#7ac74c","#c063e0","#5bc7d0"][i % 6] }} />
                <span className="alloc-name">{a.set_name}</span>
                <span className="alloc-val">{formatMoney(a.market_value)}</span>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={0.2} className="dashboard-card dashboard-movers">
          <h3 className="dashboard-card-h">Top movers</h3>
          <h4 className="movers-sub up">Gainers</h4>
          <MoverBars items={summary?.top_gainers ?? []} kind="gainers" />
          <h4 className="movers-sub down">Losers</h4>
          <MoverBars items={summary?.top_losers ?? []} kind="losers" />
        </Reveal>
      </div>

      <Reveal delay={0.24}>
        <div className="dashboard-ctas dashboard-ctas-row">
          <button className="primary" onClick={() => onNavigate("scan")}>Start scanning</button>
          <button className="link" onClick={() => onNavigate("browse")}>Browse the catalog</button>
          <button className="link" onClick={() => onNavigate("deals")}>Snipe deals</button>
          <button className="link" onClick={() => onNavigate("prices")}>Look up card prices</button>
          <button className="link" onClick={() => onNavigate("catalog")}>Browse sealed catalog</button>
          <button className="link" onClick={() => onNavigate("ledger")}>Open ledger</button>
          {unread > 0 && <button className="link" onClick={() => onNavigate("alerts")}>View alerts</button>}
          <button className="link" onClick={onWatchCard}>Watch a card</button>
        </div>
      </Reveal>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className={`kpi${tone ? ` kpi-${tone}` : ""}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
    </div>
  );
}