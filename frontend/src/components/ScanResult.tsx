import { useState } from "react";

import type { RecognizeResponse } from "../api/types";
import { statusLabel } from "../lib/format";
import CandidatePicker from "./CandidatePicker";
import CenteringPanel from "./CenteringPanel";
import PriceLine from "./PriceLine";

interface Props {
  result: RecognizeResponse;
  variant: string;
  onConfirm: (acquiredPrice: number | null) => void;
  onPick: (cardId: string, acquiredPrice: number | null) => void;
  onReject: () => void;
  onRescan: () => void;
}

export default function ScanResult({
  result,
  variant,
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

  return (
    <section className="result">
      <header className={`result-status ${status}`}>
        <span>{statusLabel(status)}</span>
        <span className="confidence">{(result.confidence * 100).toFixed(0)}%</span>
      </header>

      {card && (
        <div className="card-detail">
          {card.image_small && <img src={card.image_small} alt={card.name} />}
          <div>
            <h2>{card.name}</h2>
            <p className="card-meta">
              {card.set_name} · #{card.number}
              {card.rarity ? ` · ${card.rarity}` : ""}
            </p>
            <PriceLine cardId={card.id} variant={variant} initial={result.price} />
          </div>
        </div>
      )}

      {/* Absent whenever the border could not be measured. There is nothing to say in
          that case, so the panel does not appear at all rather than as an empty box. */}
      {result.centering && <CenteringPanel centering={result.centering} />}

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
