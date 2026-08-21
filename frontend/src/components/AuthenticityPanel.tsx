import { useEffect, useState } from "react";

import { getAuthenticity } from "../api/client";
import type { Authenticity, ConsistencyMatch } from "../api/types";

interface Props {
  scanId: number;
}

// The one-line verdict label per consistency state. Deliberately never claims
// "fake" or "real" — a mismatch is the honest ambiguity (wrong recognition OR
// counterfeit), and the full explanation travels in the server-sourced `note`.
const STATUS_LABEL: Record<ConsistencyMatch, string> = {
  match: "Printed number matches",
  mismatch: "Printed number mismatch",
  unread: "Could not read the printed number",
  no_card: "No card recognized",
};

/**
 * The honest counterfeit tool — a guide, never a verdict.
 *
 * Mirrors the Grading Studio's honest form: the one measurable auto-signal (the
 * printed collector number OCR read vs the recognized card's catalog number)
 * is surfaced with its honest ambiguity, and the rest is a user-driven physical
 * checklist the collector performs by hand. Image-forensic detection (halftone /
 * holo / sharpness / color-delta) was tested and disproven on this dataset's
 * 600x825 rectified phone crops, and zero confirmed-counterfeit samples exist to
 * calibrate a learned check against — so nothing here computes a fake/real score.
 *
 * Checklist checkboxes are local state, not persisted: like the Grading Studio's
 * sub-score sliders, they are a scratchpad for one inspection, not a stored
 * verdict. A future task that collects confirmed-counterfeit labels (mirroring
 * GradingLabel) is the only honest path to a real detector.
 */
export default function AuthenticityPanel({ scanId }: Props) {
  const [data, setData] = useState<Authenticity | null>(null);
  const [error, setError] = useState(false);
  // Scratchpad: which checklist items the collector has ticked. Never persisted.
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    setError(false);
    getAuthenticity(scanId)
      .then((a) => {
        if (!cancelled) setData(a);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [scanId]);

  if (error) {
    return (
      <section className="authenticity-panel">
        <h3 className="authenticity-headline">Authenticity check</h3>
        <p className="error">Could not load the authenticity checks.</p>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="authenticity-panel">
        <h3 className="authenticity-headline">Authenticity check</h3>
        <p className="muted small">Loading authenticity checks…</p>
      </section>
    );
  }

  const { consistency, checklist, caveat } = data;

  return (
    <section className="authenticity-panel">
      <h3 className="authenticity-headline">Authenticity check — guide, not a verdict</h3>
      <p className="authenticity-caveat muted small">{caveat}</p>

      <div className={`authenticity-consistency ${consistency.match}`}>
        <span className="consistency-status">{STATUS_LABEL[consistency.match]}</span>
        <p className="consistency-note">{consistency.note}</p>
      </div>

      <ul className="authenticity-checklist">
        {checklist.map((item) => (
          <li key={item.id} className={`checklist-item${item.applies ? "" : " na"}`}>
            <div className="checklist-head">
              <span className="checklist-title">{item.title}</span>
              {!item.applies && <span className="checklist-na muted small">N/A for this card type</span>}
            </div>
            {item.applies ? (
              <label className="checklist-row">
                <input
                  type="checkbox"
                  checked={!!checked[item.id]}
                  onChange={(e) =>
                    setChecked((prev) => ({ ...prev, [item.id]: e.target.checked }))
                  }
                />
                <span className="checklist-body">
                  <span className="checklist-what">{item.what_to_check}</span>
                  <span className="checklist-caveat muted small">{item.caveat}</span>
                </span>
              </label>
            ) : (
              <p className="checklist-what muted small">{item.what_to_check}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}