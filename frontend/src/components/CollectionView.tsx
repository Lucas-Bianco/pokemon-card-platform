import { useCallback, useEffect, useState } from "react";

import { getCollection, getValuation } from "../api/client";
import type { CollectionItem, Valuation } from "../api/types";
import { formatMoney } from "../lib/format";

interface Props {
  onBack: () => void;
}

export default function CollectionView({ onBack }: Props) {
  const [items, setItems] = useState<CollectionItem[] | null>(null);
  const [valuation, setValuation] = useState<Valuation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [fetchedItems, fetchedValuation] = await Promise.all([
        getCollection(),
        getValuation(),
      ]);
      setItems(fetchedItems);
      setValuation(fetchedValuation);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your collection.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="collection">
      <header className="collection-head">
        <h2>Your collection</h2>
        <button onClick={onBack}>Back to scanning</button>
      </header>

      {error && <p className="error">{error}</p>}

      {valuation && (
        <div className="valuation">
          <div>
            <span className="label">Market value</span>
            <strong>{formatMoney(valuation.market_value)}</strong>
          </div>
          <div>
            <span className="label">Cost basis</span>
            <strong>{formatMoney(valuation.cost_basis)}</strong>
          </div>
          <div>
            <span className="label">Unrealised</span>
            {/* With no cost basis recorded, "unrealised" would equal market value and read
                as pure profit. That is not a gain, it is missing data — say so instead. */}
            {valuation.cost_basis === 0 ? (
              <strong className="unknown">—</strong>
            ) : (
              <strong className={valuation.unrealized >= 0 ? "up" : "down"}>
                {valuation.unrealized >= 0 ? "+" : "−"}
                {formatMoney(Math.abs(valuation.unrealized))}
              </strong>
            )}
          </div>
        </div>
      )}

      {valuation && valuation.cost_basis === 0 && (
        <p className="muted small">
          No purchase prices recorded yet, so profit/loss is unknown. Enter what you paid when you
          add a card and it will start tracking.
        </p>
      )}

      {valuation && valuation.unpriced_items > 0 && (
        <p className="muted small">
          {valuation.unpriced_items} item{valuation.unpriced_items === 1 ? "" : "s"} have no market
          price yet and count as zero — never guessed.
        </p>
      )}

      {items === null && !error && <p className="muted">Loading…</p>}

      {items !== null && items.length === 0 && (
        <p className="muted">Nothing here yet. Scan a card and tap “add to collection”.</p>
      )}

      {items !== null && items.length > 0 && (
        <ul className="collection-list">
          {items.map((item) => (
            <li key={item.id}>
              <span className="qty">×{item.quantity}</span>
              <span className="collection-text">
                <strong>{item.card_name}</strong>
                <span className="collection-meta">
                  {item.variant}
                  {item.acquired_price !== null && ` · paid ${formatMoney(item.acquired_price)}`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
