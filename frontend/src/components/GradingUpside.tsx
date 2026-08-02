import { useEffect, useState } from "react";

import { getGradingUpside } from "../api/client";
import type { GradingTier, GradingUpside as GradingUpsideData } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

interface Props {
  cardId: string;
  variant: string;
}

type State =
  | { kind: "loading" }
  | { kind: "loaded"; data: GradingUpsideData }
  | { kind: "error"; message: string };

// One tier row. `market` null → an em dash + "no market price" (the same
// convention PortfolioView uses for an unpriced holding), never a $0.00.
function TierRow({ label, tier }: { label: string; tier: GradingTier | null }) {
  if (tier === null) {
    return (
      <div className="grading-tier">
        <dt>{label}</dt>
        <dd>
          <span className="unknown">—</span>
          <span className="price-meta muted small">no market price</span>
        </dd>
      </div>
    );
  }
  return (
    <div className="grading-tier">
      <dt>{label}</dt>
      <dd>
        <strong>{formatMoney(tier.market)}</strong>
        <span className="price-meta">
          {tier.source} · {formatStaleness(tier.source_updated_at)}
        </span>
      </dd>
    </div>
  );
}

/**
 * The raw-vs-graded price spread — a spread, not a grade prediction. Every null
 * path renders an honest em dash and a reason, never a fabricated $0 or a
 * fake EV. Mirrors CenteringPanel's voice ("a ceiling, not a grade") and
 * PortfolioView's unpriced convention ("— no market price").
 */
export default function GradingUpside({ cardId, variant }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getGradingUpside(cardId, variant);
        if (!cancelled) setState({ kind: "loaded", data });
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Could not load the grading spread.",
          });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [cardId, variant]);

  if (state.kind === "loading") {
    return <p className="grading-upside muted small">Checking grading spread…</p>;
  }
  if (state.kind === "error") {
    // An honest error, never a fake panel dressed up as data.
    return <p className="grading-upside error">{state.message}</p>;
  }

  const { data } = state;
  const gradedUnavailable = data.graded_prices_unavailable;

  return (
    <section className="grading-upside">
      <h3 className="grading-upside-headline">Grading upside — a spread, not a prediction</h3>
      <p className="grading-upside-sub">
        The gap between a raw card and its graded comps, before any fee. A wide spread does not mean
        your card grades a 10 — it only says what a 10 is worth if it did.
      </p>

      <dl className="grading-tiers">
        <TierRow label="Raw" tier={data.raw_price} />
        {gradedUnavailable ? (
          <>
            <div className="grading-tier">
              <dt>PSA 9</dt>
              <dd>
                <span className="unknown">—</span>
              </dd>
            </div>
            <div className="grading-tier">
              <dt>PSA 10</dt>
              <dd>
                <span className="unknown">—</span>
              </dd>
            </div>
          </>
        ) : (
          <>
            <TierRow label="PSA 9" tier={data.psa9} />
            <TierRow label="PSA 10" tier={data.psa10} />
          </>
        )}
      </dl>

      <div className="grading-fee">
        <span className="label">Grading fee</span>
        <strong>{formatMoney(data.grading_fee)}</strong>
      </div>

      <div className="grading-upside-value">
        <span className="label">Upside to 10</span>
        {data.upside_to_10 !== null ? (
          <strong className="up">+{formatMoney(data.upside_to_10)}</strong>
        ) : (
          // Null when either raw or psa10 is missing — fabricating an EV from a
          // missing input would be confidently-wrong. Say what is missing.
          <span className="unknown">—</span>
        )}
      </div>

      {gradedUnavailable && (
        <p className="grading-unavailable-note muted small">
          Graded prices unavailable — set a graded-price provider key
          (CARDPLATFORM_GRADED_PRICE_API_KEY) to enable.
        </p>
      )}

      {data.upside_to_10 === null && !gradedUnavailable && (
        <p className="muted small">
          {data.raw_price === null && data.psa10 === null
            ? "Need both a raw price and a PSA 10 sold comp to compute the upside."
            : data.raw_price === null
              ? "Need a raw price to compute the upside to a 10."
              : "Need a PSA 10 sold comp to compute the upside to a 10."}
        </p>
      )}

      <ul className="centering-caveats">
        <li>This is the upside spread, not a grade prediction. Predicting a grade needs labeled data we're only starting to collect.</li>
      </ul>
    </section>
  );
}