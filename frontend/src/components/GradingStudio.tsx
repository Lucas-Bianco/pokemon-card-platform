import { useState } from "react";

import type { Centering, Grader } from "../api/types";
import { estimateGrade, type Confidence, type SubScores } from "../lib/gradeEstimate";

interface Props {
  centering: Centering | null;
  grader?: Grader;
}

const SUBS: Array<{ key: keyof SubScores; label: string; hint: string }> = [
  { key: "corners", label: "Corners", hint: "Sharp, unfurred, no whitening." },
  { key: "edges", label: "Edges", hint: "Clean, no chipping or wear." },
  { key: "surface", label: "Surface", hint: "No scratches, prints, or indentations." },
];

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const DEFAULTS: SubScores = { corners: 9, edges: 9, surface: 9 };

function barPct(v: number): number {
  return ((v - 1) / 9) * 100;
}

/**
 * A pre-submission self-assessment — a calculator of the user's corner/edge/surface
 * estimates plus the one measured sub-grade (centering), NOT a prediction from the
 * image and NOT a guarantee. See gradeEstimate.ts for the (transparent, deterministic)
 * math and the honesty framing. Centering is measured server-side; the rest are the
 * user's own sub-score estimates, because the project has no labelled data to learn
 * corners/edges/surface from (grading/centering.py declines them for exactly that reason).
 */
export default function GradingStudio({ centering, grader = "PSA" }: Props) {
  const [subs, setSubs] = useState<SubScores>(DEFAULTS);
  const [activeGrader, setActiveGrader] = useState<Grader>(grader);

  const est = estimateGrade(subs, centering, activeGrader);

  function reset() {
    setSubs(DEFAULTS);
    setActiveGrader(grader);
  }

  return (
    <section className="grading-studio">
      <h3 className="grading-studio-headline">Grading studio — estimate a grade band</h3>
      <p className="grading-studio-sub">
        A pre-submission self-assessment. Centering is measured from your scan; rate corners,
        edges and surface yourself for an estimated grade band. A calculator of your inputs, not a
        prediction from the image and not a guarantee.
      </p>

      <div className="grading-studio-grade">
        <div className="grade-estimate">
          <span className="grade-label">Estimated {activeGrader} grade</span>
          <strong className="grade-number">≈{est.estimate}</strong>
          <span className={`grade-confidence ${est.confidence}`}>
            {CONFIDENCE_LABEL[est.confidence]}
          </span>
        </div>
        <div className="grade-centering">
          <span className="label">Centering ceiling</span>
          {est.centeringMeasured ? (
            <span>PSA {est.centeringCap}</span>
          ) : (
            <span className="unknown">unmeasured</span>
          )}
        </div>
      </div>

      <div className="grading-studio-subs">
        {SUBS.map((s) => (
          <label className="sub-score" key={s.key}>
            <span className="sub-head">
              <span className="sub-name">{s.label}</span>
              <span className="sub-value">{subs[s.key].toFixed(1)}</span>
            </span>
            <input
              type="range"
              min={1}
              max={10}
              step={0.5}
              value={subs[s.key]}
              aria-label={s.label}
              onChange={(e) =>
                setSubs((prev) => ({ ...prev, [s.key]: Number(e.target.value) }))
              }
            />
            <span className="sub-bar" aria-hidden="true">
              <span className="sub-fill" style={{ width: `${barPct(subs[s.key])}%` }} />
            </span>
            <span className="sub-hint muted small">{s.hint}</span>
          </label>
        ))}
      </div>

      {est.binding.length > 0 && (
        <p className="grading-studio-binding muted small">
          Limited by: {est.binding.join(", ")}.
        </p>
      )}

      <div className="grading-studio-grader">
        <label>
          <span>Grader</span>
          <select
            value={activeGrader}
            onChange={(e) => setActiveGrader(e.target.value as Grader)}
            aria-label="Grader"
          >
            <option value="PSA">PSA</option>
            <option value="CGC">CGC</option>
            <option value="BGS">BGS</option>
          </select>
        </label>
        <button type="button" className="link" onClick={reset}>
          Reset estimates
        </button>
      </div>

      <ul className="grading-studio-caveats">
        {est.caveats.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}