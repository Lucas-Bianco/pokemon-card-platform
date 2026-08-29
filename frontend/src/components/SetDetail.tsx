import { useEffect, useState } from "react";

import { getSetCompletion } from "../api/client";
import { formatMoney } from "../lib/format";
import type { SetCompletion } from "../api/types";

interface Props {
  setId: string;
  onBack: () => void;
  onSelectCard: (cardId: string) => void;
}

export default function SetDetail({ setId, onBack, onSelectCard }: Props) {
  const [data, setData] = useState<SetCompletion | null>(null);
  const [error, setError] = useState(false);
  // "Show only missing" — collapses the checklist to just the gaps, the
  // thing a collector chasing completion actually wants to see. Default off
  // so the full ordered checklist (and its order-sensitive assertions) still
  // renders. Reset when the set changes so a stale filter never carries over.
  const [missingOnly, setMissingOnly] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    // A new set resets the filter so a stale "missing only" never carries
    // over from the set you just left.
    setMissingOnly(false);
    getSetCompletion(setId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [setId]);

  if (error) {
    return (
      <section className="set-detail">
        <button className="link card-back" onClick={onBack}>← Back</button>
        <p className="error">Couldn't load this set.</p>
      </section>
    );
  }
  if (!data) {
    return (
      <section className="set-detail">
        <button className="link card-back" onClick={onBack}>← Back</button>
        <div className="skeleton skeleton-block" aria-label="Loading set" />
      </section>
    );
  }

  const s = data.summary;
  const pct = Math.round(s.pct_complete * 100);
  const complete = s.missing === 0;
  const costText =
    s.est_cost_to_complete === null ? "—" : formatMoney(s.est_cost_to_complete);

  return (
    <section className="set-detail">
      <button className="link card-back" onClick={onBack}>← Back</button>

      <div className="set-detail-head">
        <h2>{data.name}</h2>
        <p className="card-meta">
          {data.series ? `${data.series} · ` : ""}
          {data.release_date ? data.release_date.slice(0, 4) : ""}
        </p>
      </div>

      <div className="set-detail-summary">
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value">{s.owned} / {s.checklist_size}</span>{" "}
          <span className="muted small">owned</span>
        </div>
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value">{pct}%</span>
          <span className="muted small">complete</span>
        </div>
        <div className="set-detail-kpi">
          <span className="set-detail-kpi-value set-detail-cost">
            {complete ? "Complete" : costText}
          </span>
          <span className="muted small">est. cost to complete</span>
        </div>
      </div>

      {!complete && s.unpriced_missing > 0 && (
        <p className="muted small set-detail-unpriced">
          unpriced: {s.unpriced_missing} card{s.unpriced_missing === 1 ? "" : "s"} not in the price index
        </p>
      )}

      {/* The completion action loop: a collector opens a set to see what to
          chase next. "Show only missing" collapses the checklist to just the
          gaps instead of scrolling past every card already owned. Only shown
          when there's something to filter to (a complete set has no gaps). */}
      {!complete && (
        <label className="checklist-filter">
          <input
            type="checkbox"
            checked={missingOnly}
            onChange={(e) => setMissingOnly(e.target.checked)}
          />
          <span>Show only missing ({s.missing})</span>
        </label>
      )}

      <ul className="checklist">
        {(missingOnly ? data.cards.filter((c) => !c.owned) : data.cards).map((c) => (
          <li key={c.card_id}>
            <button className="checklist-tile" onClick={() => onSelectCard(c.card_id)}>
              <span className="checklist-thumb-wrap">
                {c.image_small ? (
                  <img src={c.image_small} alt="" className="checklist-thumb" />
                ) : (
                  <span className="checklist-thumb placeholder" aria-hidden="true" />
                )}
              </span>
              <span className="checklist-text">
                <span className="checklist-name">{c.name}</span>
                <span className="checklist-meta muted small">
                  #<span className="checklist-num">{c.number}</span>{c.rarity ? ` · ${c.rarity}` : ""}
                </span>
                {c.owned ? (
                  <span className="checklist-owned">Owned</span>
                ) : c.market !== null ? (
                  <span className="checklist-price">
                    {formatMoney(c.market)}
                    <span className="muted small">
                      {" "}{c.source}
                      {c.source_updated_at ? ` · as of ${c.source_updated_at}` : ""}
                    </span>
                  </span>
                ) : (
                  <span className="checklist-price muted small">no market price</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}