// Trade-up / sell-now simulator (roadmap row 19) — the honest form of an
// exit-strategy tool. For a card you own, compares two exit legs:
//
//   * Sell raw now — proven eBay sold-comps median, net of an estimated selling
//     fee. Realised transactions, not a listed ask.
//   * Grade then sell — graded market, net of the grading fee + selling fee.
//     Assumes the card achieves the target grade; a measured centering cap
//     below the target flags that grade as not reachable.
//
// The market reference (a listed ask) is shown for context, never used as the
// sell price. The recommendation is descriptive of which net is higher, never a
// forecast. Every null leg renders an em dash + the note, never a fabricated
// $0. Mirrors GradingUpside's load/error/empty voice and the project's sacred
// honesty conventions. Read-only.
import { useEffect, useState } from "react";

import { getTradeUp } from "../api/client";
import type { TradeUpAssessment, TradeUpLeg } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

interface Props {
  cardId: string;
  variant: string;
  /** A measured PSA centering ceiling from a scan, to pre-fill the cap box and
   * rule out grades the card can't reach. Optional — null/omitted means
   * "centering unmeasured", the honest default. */
  initialCenteringCap?: number | null;
}

type State =
  | { kind: "loading" }
  | { kind: "loaded"; data: TradeUpAssessment }
  | { kind: "error"; message: string };

// Grades the user can target for the grade leg. PSA/CGC/BGS grade in whole and
// half points, but the graded-price provider keys its tiers by whole grade, so
// the choice is constrained to the tiers that actually carry a market figure.
const GRADES = [10, 9, 8] as const;

function LegRow({ leg }: { leg: TradeUpLeg }) {
  // A null net is an honest "can't estimate" — the note says why, the UI shows
  // an em dash, never a fabricated $0.00.
  const priced = leg.net !== null;
  return (
    <div className={`tradeup-leg${priced ? "" : " unpriced"}`}>
      <dt>{leg.label}</dt>
      <dd>
        {priced ? (
          <>
            <strong className="tradeup-net">{formatMoney(leg.net)}</strong>
            <span className="price-meta muted small">
              {formatMoney(leg.gross)} gross
              {leg.fee !== null ? ` − ${formatMoney(leg.fee)} fees` : ""}
            </span>
          </>
        ) : (
          <>
            <span className="unknown">—</span>
            <span className="price-meta muted small">no estimate</span>
          </>
        )}
        <span className="tradeup-note muted small">
          {leg.note}
          {leg.source ? ` · ${leg.source}` : ""}
          {leg.source ? ` · ${formatStaleness(leg.source_updated_at)}` : ""}
          {leg.evidence_count !== null && leg.evidence_count > 0
            ? ` · ${leg.evidence_count} sale${leg.evidence_count === 1 ? "" : "s"}`
            : ""}
        </span>
      </dd>
    </div>
  );
}

export default function TradeUp({ cardId, variant, initialCenteringCap = null }: Props) {
  const [grade, setGrade] = useState<number>(10);
  const [centeringInput, setCenteringInput] = useState<string>(
    initialCenteringCap !== null && initialCenteringCap !== undefined
      ? String(initialCenteringCap)
      : "",
  );
  const [state, setState] = useState<State>({ kind: "loading" });

  // Empty string -> no cap (centering unmeasured). A real integer -> that cap.
  const centeringCap: number | null =
    centeringInput.trim() === "" ? null : Number(centeringInput);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getTradeUp(cardId, variant, {
          grade,
          // Only send a cap when the user entered a real whole number; a blank
          // or NaN box means "centering unmeasured", which is the honest default.
          centeringCap:
            centeringCap !== null && Number.isFinite(centeringCap)
              ? Math.round(centeringCap)
              : null,
        });
        if (!cancelled) setState({ kind: "loaded", data });
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Could not load the trade-up assessment.",
          });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [cardId, variant, grade, centeringCap]);

  return (
    <section className="tradeup" aria-label="Trade-up or sell-now simulator">
      <h3 className="tradeup-headline">Trade up or sell now — two honest exits</h3>
      <p className="tradeup-sub">
        What you'd pocket from each exit, net of fees, from proven sales and graded markets — not a
        forecast of what the card will do.
      </p>

      <div className="tradeup-controls">
        <label className="tradeup-control">
          <span className="muted small">Target grade</span>
          <select
            value={grade}
            onChange={(e) => setGrade(Number(e.target.value))}
            aria-label="Target grade"
          >
            {GRADES.map((g) => (
              <option key={g} value={g}>
                PSA {g}
              </option>
            ))}
          </select>
        </label>
        <label className="tradeup-control">
          <span className="muted small">Centering cap (optional)</span>
          <input
            type="number"
            min={1}
            max={10}
            inputMode="numeric"
            placeholder="e.g. 9"
            value={centeringInput}
            onChange={(e) => setCenteringInput(e.target.value)}
            aria-label="Centering cap"
          />
        </label>
      </div>

      {state.kind === "loading" && (
        <p className="tradeup muted small">Assessing exit legs…</p>
      )}
      {state.kind === "error" && (
        <p className="tradeup error">{state.message}</p>
      )}

      {state.kind === "loaded" && (
        <>
          <dl className="tradeup-legs">
            <LegRow leg={state.data.raw_leg} />
            <LegRow leg={state.data.grade_leg} />
          </dl>

          <div className="tradeup-reference">
            <span className="label">Market reference</span>
            <strong>{formatMoney(state.data.market_reference)}</strong>
            <span className="price-meta muted small">
              {state.data.market_reference_source
                ? `${state.data.market_reference_source} · ${formatStaleness(state.data.market_reference_source_updated_at)}`
                : "no listed ask"}
            </span>
            <span className="tradeup-note muted small">a listed ask, for context — not the sell price</span>
          </div>

          <div className="tradeup-recommendation">
            <span className="label">Honest read</span>
            {state.data.recommendation !== null ? (
              <strong className={
                state.data.recommendation === "grade" ? "up" : "neutral"
              }>
                {state.data.recommendation === "grade" ? "Grade, then sell" : "Sell raw now"}
              </strong>
            ) : (
              <span className="unknown">—</span>
            )}
            <span className="tradeup-note muted small">{state.data.recommendation_note}</span>
          </div>

          {state.data.centering_blocks_grading && (
            <p className="tradeup-block-note muted small">
              The centering cap you entered is below the target grade, so grading to that grade is
              not a real option for this card — the figure is shown for reference only.
            </p>
          )}

          <ul className="centering-caveats">
            {(state.data.caveats ?? []).map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}