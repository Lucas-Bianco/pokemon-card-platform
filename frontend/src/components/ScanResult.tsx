import { useEffect, useState } from "react";

import { getGradeLabel, postGradeLabel } from "../api/client";
import type { Grader, GradingLabel, RecognizeResponse } from "../api/types";
import { statusLabel } from "../lib/format";
import AuthenticityPanel from "./AuthenticityPanel";
import CandidatePicker from "./CandidatePicker";
import CenteringPanel from "./CenteringPanel";
import GradingStudio from "./GradingStudio";
import GradingUpside from "./GradingUpside";
import PriceLine from "./PriceLine";

interface Props {
  result: RecognizeResponse;
  variant: string;
  // The logged scan's id, so a self-annotation can POST to /scans/{id}/grade-label.
  // Null when no scan was logged (e.g. a test render or a recognition failure that
  // never recorded) — the annotation affordance is hidden in that case, because a
  // label must describe a real scan, not a free-standing card id.
  scanId?: number | null;
  onConfirm: (acquiredPrice: number | null) => void;
  onPick: (cardId: string, acquiredPrice: number | null) => void;
  onReject: () => void;
  onRescan: () => void;
}

// A grade must be a real number 1–10 in half-steps (PSA/CGC/BGS all use 0.5
// increments above the integer floor). Returns the parsed number or null when
// the input is empty/invalid/out of range — the submit button stays disabled.
function parseGrade(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 1 || n > 10) return null;
  // Half-steps only: 9.5 is valid, 9.25 is not. Round to the nearest half and
  // check it didn't move — this rejects 9.7 without inventing a rounding.
  if (Math.abs(n - Math.round(n * 2) / 2) > 1e-9) return null;
  return n;
}

export default function ScanResult({
  result,
  variant,
  scanId = null,
  onConfirm,
  onPick,
  onReject,
  onRescan,
}: Props) {
  const { card, status } = result;
  // Optional. Without a cost basis there is no profit/loss to compute later, but
  // guessing one would be worse than leaving it unknown.
  const [paid, setPaid] = useState("");
  const acquiredPrice = paid.trim() === "" ? null : Number(paid);

  // --- Self-annotation state ------------------------------------------------
  // A label already attached to this scan (fetched on mount so a re-scan of the
  // same card shows the recorded grade read-only instead of a blank form).
  const [existing, setExisting] = useState<GradingLabel | null>(null);
  const [labelLoading, setLabelLoading] = useState(false);
  const [labelError, setLabelError] = useState<string | null>(null);

  // Form fields for recording a new grade. grade/grader are required; cert and
  // notes are optional and sent as null when blank (not empty strings).
  const [grader, setGrader] = useState<Grader>("PSA");
  const [grade, setGrade] = useState("");
  const [cert, setCert] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<GradingLabel | null>(null);

  // Fetch any existing label for this scan when we have one. "No label yet" is
  // the common case (404 → null), not an error.
  useEffect(() => {
    if (scanId === null) return;
    let cancelled = false;
    setLabelLoading(true);
    setLabelError(null);
    getGradeLabel(scanId)
      .then((label) => {
        if (!cancelled) setExisting(label);
      })
      .catch((err) => {
        if (!cancelled) {
          setLabelError(err instanceof Error ? err.message : "Could not load the existing label.");
        }
      })
      .finally(() => {
        if (!cancelled) setLabelLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scanId]);

  const gradeValue = parseGrade(grade);
  const canSubmit = scanId !== null && gradeValue !== null && !submitting;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (scanId === null || gradeValue === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const label = await postGradeLabel(scanId, {
        grade: gradeValue,
        grader,
        cert_number: cert.trim() === "" ? null : cert.trim(),
        notes: notes.trim() === "" ? null : notes.trim(),
      });
      setRecorded(label);
      setExisting(label);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Could not record the grade.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="result">
      <header className={`result-status ${status}`}>
        <span>{statusLabel(status)}</span>
        <span className="confidence">{(result.confidence * 100).toFixed(0)}%</span>
      </header>

      {card && (
        <div className="card-detail">
          {card.image_small && <img src={card.image_small} alt={card.name} />}
          <div className="card-detail-text">
            <h2>{card.name}</h2>
            <p className="card-meta">
              {card.set_name} · #{card.number}
              {card.rarity ? ` · ${card.rarity}` : ""}
            </p>
            <PriceLine cardId={card.id} variant={variant} initial={result.price} />
          </div>
        </div>
      )}

      {/* The grading spread only makes sense once a card is identified — it is
          keyed on card_id. Hidden for not_found, where there is no card to price. */}
      {card && <GradingUpside cardId={card.id} variant={variant} />}

      {/* Absent whenever the border could not be measured. There is nothing to say in
          that case, so the panel does not appear at all rather than as an empty box. */}
      {result.centering && <CenteringPanel centering={result.centering} />}

      {/* A pre-submission self-assessment: the measured centering ceiling plus the
          user's own corner/edge/surface sub-score estimates -> an estimated grade
          band. A calculator of the user's inputs, not a prediction from the image.
          Card-gated like GradingUpside/CenteringPanel — no card, no estimate. */}
      {card && <GradingStudio centering={result.centering} grader="PSA" />}

      {/* The honest counterfeit tool: the one measurable auto-signal (printed
          number vs catalog) + a user-driven physical checklist. A guide, never a
          verdict — see AuthenticityPanel. Card-gated like GradingStudio: without
          a recognized card there is no catalog number to cross-check. */}
      {card && scanId !== null && <AuthenticityPanel scanId={scanId} />}

      {result.collector_number_read && (
        <p className="ocr-note">Read card number: {result.collector_number_read}</p>
      )}

      {(status === "confident" || status === "ambiguous") && (
        <label className="paid">
          <span>What you paid (optional)</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            placeholder="—"
            value={paid}
            onChange={(event) => setPaid(event.target.value)}
          />
        </label>
      )}

      {card && scanId !== null && (
        <div className="grading-label-section">
          {labelError && <p className="error">{labelError}</p>}
          {labelLoading && <p className="muted small">Checking for a recorded grade…</p>}
          {existing && !labelLoading && (
            <div className="grading-label-display">
              <h4>Recorded grade</h4>
              <p className="muted small">
                {existing.grader} {existing.grade}
                {existing.cert_number ? ` · cert ${existing.cert_number}` : ""}
                {existing.notes ? ` · ${existing.notes}` : ""}
              </p>
            </div>
          )}
          {!existing && !labelLoading && (
            <form className="grading-label-form" onSubmit={handleSubmit}>
              <h4>Record this card's grade</h4>
              <p className="muted small">
                Got it back from PSA/CGC/BGS? Enter the grade — this is the project's only honest
                labelled dataset.
              </p>
              <label>
                <span>Grader</span>
                <select value={grader} onChange={(e) => setGrader(e.target.value as Grader)}>
                  <option value="PSA">PSA</option>
                  <option value="CGC">CGC</option>
                  <option value="BGS">BGS</option>
                </select>
              </label>
              <label>
                <span>Grade</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  step="0.5"
                  inputMode="decimal"
                  placeholder="e.g. 9"
                  value={grade}
                  onChange={(e) => setGrade(e.target.value)}
                />
              </label>
              <label>
                <span>Cert (optional)</span>
                <input
                  type="text"
                  placeholder="—"
                  value={cert}
                  onChange={(e) => setCert(e.target.value)}
                />
              </label>
              <label>
                <span>Notes (optional)</span>
                <input
                  type="text"
                  placeholder="—"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </label>
              {submitError && <p className="error">{submitError}</p>}
              {recorded && <p className="muted small">Grade recorded — thanks.</p>}
              <button type="submit" className="primary" disabled={!canSubmit}>
                {submitting ? "Recording…" : "Record grade"}
              </button>
            </form>
          )}
        </div>
      )}

      {status === "confident" && (
        <div className="actions">
          <button className="primary" onClick={() => onConfirm(acquiredPrice)}>
            Correct — add to collection
          </button>
          <button onClick={onReject}>Wrong card</button>
        </div>
      )}

      {status === "ambiguous" && (
        <CandidatePicker
          candidates={result.candidates}
          onPick={(cardId) => onPick(cardId, acquiredPrice)}
          onReject={onReject}
        />
      )}

      {status === "not_found" && (
        <p className="muted">
          No card detected. Try a darker background, and leave a margin around the card.
        </p>
      )}

      <button className="rescan" onClick={onRescan}>
        Scan another
      </button>
    </section>
  );
}