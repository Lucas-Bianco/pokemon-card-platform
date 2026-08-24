// Collection insurance value — replacement-value bands (conservative / median /
// aggressive) from the same proven price snapshots the rest of the app uses, plus a
// printable per-card schedule. Honest empty states: an unpriced card is excluded from
// the totals and counted, never shown as $0; every figure carries source + staleness.
// The bands are an indicative estimate, not a binding appraisal.
import { useEffect, useState } from "react";

import { getInsuranceValue } from "../api/client";
import type { InsuranceValue as InsuranceValueT } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

export default function InsuranceValue() {
  const [data, setData] = useState<InsuranceValueT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSchedule, setShowSchedule] = useState(false);

  useEffect(() => {
    let alive = true;
    setError(null);
    getInsuranceValue()
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Could not load insurance value.");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <p className="error small">{error}</p>;
  if (data === null) return <div className="skeleton skeleton-block" aria-label="Loading insurance value" />;

  // Every figure is zero for an empty collection — that is honest (nothing to value),
  // not a fabrication, so it renders. The caveat below says what the bands are.
  return (
    <section className="insurance" aria-label="Collection insurance value">
      <h3>Insurance value</h3>
      <div className="insurance-bands">
        <div className="insurance-band">
          <span className="label">Conservative</span>
          <strong>{formatMoney(data.conservative)}</strong>
          <span className="muted small">low · replacement floor</span>
        </div>
        <div className="insurance-band">
          <span className="label">Median</span>
          <strong>{formatMoney(data.median)}</strong>
          <span className="muted small">market</span>
        </div>
        <div className="insurance-band">
          <span className="label">Aggressive</span>
          <strong>{formatMoney(data.aggressive)}</strong>
          <span className="muted small">high · replacement ceiling</span>
        </div>
      </div>
      <p className="muted small">
        {data.priced_items} priced / {data.unpriced_items} unpriced
        {data.unpriced_items > 0 ? " — unpriced cards are excluded, never guessed at $0" : ""}
      </p>
      <p className="insurance-caveat muted small">{data.caveat}</p>

      <button type="button" className="link insurance-toggle" onClick={() => setShowSchedule((v) => !v)}>
        {showSchedule ? "Hide" : "View"} printable schedule
      </button>

      {showSchedule && (
        <div className="insurance-schedule-wrap">
          <table className="insurance-schedule">
            <thead>
              <tr>
                <th>Card</th>
                <th className="col-variant">Variant</th>
                <th>Qty</th>
                <th>Low</th>
                <th>Market</th>
                <th>High</th>
                <th className="col-source">Source</th>
              </tr>
            </thead>
            <tbody>
              {data.schedule.map((line) => (
                <tr key={`${line.card_id}-${line.variant}`} className={line.priced ? "" : "unpriced"}>
                  <td data-label="Card" className="name">
                    {line.card_name}
                    <span className="muted small d-block">{line.set_name}</span>
                  </td>
                  <td data-label="Variant" className="col-variant">
                    {line.variant}
                  </td>
                  <td data-label="Qty">×{line.quantity}</td>
                  <td data-label="Low">{formatMoney(line.low)}</td>
                  <td data-label="Market">{formatMoney(line.market)}</td>
                  <td data-label="High">{formatMoney(line.high)}</td>
                  <td data-label="Source" className="col-source muted small">
                    {line.priced
                      ? `${line.source ?? ""}${line.source ? " · " : ""}${formatStaleness(line.source_updated_at)}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="primary insurance-print" onClick={() => window.print()}>
            Print schedule
          </button>
        </div>
      )}
    </section>
  );
}