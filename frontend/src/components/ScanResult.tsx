import type { RecognizeResponse } from "../api/types";
import { statusLabel } from "../lib/format";
import CandidatePicker from "./CandidatePicker";
import PriceLine from "./PriceLine";

interface Props {
  result: RecognizeResponse;
  variant: string;
  onConfirm: () => void;
  onPick: (cardId: string) => void;
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

      {result.collector_number_read && (
        <p className="ocr-note">Read card number: {result.collector_number_read}</p>
      )}

      {status === "confident" && (
        <div className="actions">
          <button className="primary" onClick={onConfirm}>
            Correct — add to collection
          </button>
          <button onClick={onReject}>Wrong card</button>
        </div>
      )}

      {status === "ambiguous" && (
        <CandidatePicker candidates={result.candidates} onPick={onPick} onReject={onReject} />
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
