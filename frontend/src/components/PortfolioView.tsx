import { Fragment, useCallback, useEffect, useState } from "react";

import {
  getPriceHistory,
  getPortfolio,
  patchCollectionItem,
  removeFromCollection,
} from "../api/client";
import type { Portfolio, PortfolioItem, PricePoint } from "../api/types";
import { formatMoney } from "../lib/format";
import PriceChart from "./PriceChart";

interface Props {
  onBack: () => void;
}

export default function PortfolioView({ onBack }: Props) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The holding row whose "History" chart is open, plus its fetched points.
  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const [historyPoints, setHistoryPoints] = useState<PricePoint[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPortfolio(await getPortfolio());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your portfolio.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleHistory = useCallback(async (item: PortfolioItem) => {
    setHistoryFor(item.id);
    setHistoryPoints(null);
    setHistoryError(null);
    try {
      const history = await getPriceHistory(item.card_id, item.variant);
      setHistoryPoints(history.points);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Could not load price history.");
    }
  }, []);

  const handleRemove = useCallback(
    async (item: PortfolioItem) => {
      try {
        await removeFromCollection(item.card_id, item.variant, item.quantity);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not remove the item.");
      }
    },
    [load],
  );

  const startEdit = useCallback((item: PortfolioItem) => {
    setEditing(item.id);
    setEditPrice(item.acquired_price !== null ? String(item.acquired_price) : "");
  }, []);

  const saveEdit = useCallback(
    async (item: PortfolioItem) => {
      const trimmed = editPrice.trim();
      const acquiredPrice = trimmed === "" ? null : Number(trimmed);
      if (acquiredPrice !== null && Number.isNaN(acquiredPrice)) {
        return; // ignore non-numeric input rather than sending garbage
      }
      setSaving(true);
      try {
        await patchCollectionItem(item.id, { acquired_price: acquiredPrice });
        setEditing(null);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not save the cost basis.");
      } finally {
        setSaving(false);
      }
    },
    [editPrice, load],
  );

  const summary = portfolio?.summary;

  return (
    <section className="portfolio">
      <header className="collection-head">
        <h2>Your portfolio</h2>
        <button onClick={onBack}>Back to scanning</button>
      </header>

      {error && <p className="error">{error}</p>}

      {summary && (
        <div className="valuation">
          <div>
            <span className="label">Market value</span>
            <strong>{formatMoney(summary.market_value)}</strong>
          </div>
          <div>
            <span className="label">Cost basis</span>
            <strong>{formatMoney(summary.cost_basis)}</strong>
          </div>
          <div>
            <span className="label">Unrealised</span>
            {/* With no cost basis recorded, "unrealised" would equal market value and read
                as pure profit. That is not a gain, it is missing data — say so instead. */}
            {summary.cost_basis === 0 ? (
              <strong className="unknown">—</strong>
            ) : (
              <strong className={summary.unrealized >= 0 ? "up" : "down"}>
                {summary.unrealized >= 0 ? "+" : "−"}
                {formatMoney(Math.abs(summary.unrealized))}
              </strong>
            )}
          </div>
          <div>
            <span className="label">Priced / unpriced</span>
            <strong>
              {summary.priced_items} / {summary.unpriced_items}
            </strong>
          </div>
        </div>
      )}

      {summary && summary.cost_basis === 0 && (
        <p className="muted small">
          No purchase prices recorded yet, so profit/loss is unknown. Enter what you paid when you
          add a card (or edit a holding below) and it will start tracking.
        </p>
      )}

      {summary && summary.unpriced_items > 0 && (
        <p className="muted small">
          {summary.unpriced_items} item{summary.unpriced_items === 1 ? "" : "s"} have no market
          price yet and count as zero — never guessed.
        </p>
      )}

      {summary && summary.allocation.length > 1 && (
        <div className="allocation">
          <h3>Allocation by set</h3>
          <ul>
            {summary.allocation.map((a) => (
              <li key={a.set_id}>
                <strong>{a.set_name}</strong>
                <span className="muted small">
                  {" "}
                  {formatMoney(a.market_value)} · {a.item_count} item
                  {a.item_count === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary && summary.top_gainers.length > 0 && (
        <div className="movers">
          <h3>Top movers</h3>
          <ul>
            {summary.top_gainers.map((m) => (
              <li key={`g-${m.id}`} className="up">
                {m.card_name} +{formatMoney(m.unrealized)}
              </li>
            ))}
            {summary.top_losers.map((m) => (
              <li key={`l-${m.id}`} className="down">
                {m.card_name} −{formatMoney(Math.abs(m.unrealized as number))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {portfolio === null && !error && <p className="muted">Loading…</p>}

      {portfolio !== null && portfolio.items.length === 0 && (
        <p className="muted">Nothing here yet. Scan a card and tap “add to collection”.</p>
      )}

      {portfolio !== null && portfolio.items.length > 0 && (
        <table className="portfolio-table">
          <thead>
            <tr>
              <th>Qty</th>
              <th>Card</th>
              <th>Variant</th>
              <th>Set</th>
              <th>Paid</th>
              <th>Market</th>
              <th>Unrealised</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {portfolio.items.map((item) => (
              <Fragment key={item.id}>
                <tr>
                  <td>×{item.quantity}</td>
                  <td className="name">{item.card_name}</td>
                  <td>{item.variant}</td>
                  <td className="muted">{item.set_name}</td>
                  <td>
                    {editing === item.id ? (
                      <input
                        className="edit-price"
                        type="number"
                        step="0.01"
                        value={editPrice}
                        onChange={(e) => setEditPrice(e.target.value)}
                        placeholder="paid"
                        aria-label={`Paid for ${item.card_name}`}
                      />
                    ) : (
                      formatMoney(item.acquired_price)
                    )}
                  </td>
                  <td>
                    {item.market_price !== null ? (
                      <span>
                        {formatMoney(item.market_price)}
                        {item.market_source_updated_at && (
                          <span className="muted small"> as of {item.market_source_updated_at}</span>
                        )}
                      </span>
                    ) : (
                      <span className="unpriced">
                        —<span className="muted small"> no market price</span>
                      </span>
                    )}
                  </td>
                  <td>
                    {item.unrealized === null ? (
                      <span className="unknown">—</span>
                    ) : (
                      <strong className={item.unrealized >= 0 ? "up" : "down"}>
                        {item.unrealized >= 0 ? "+" : "−"}
                        {formatMoney(Math.abs(item.unrealized))}
                      </strong>
                    )}
                  </td>
                  <td className="actions">
                    {editing === item.id ? (
                      <>
                        <button onClick={() => saveEdit(item)} disabled={saving}>
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button className="link" onClick={() => setEditing(null)}>
                          cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="link"
                          onClick={() =>
                            historyFor === item.id ? setHistoryFor(null) : handleHistory(item)
                          }
                        >
                          History
                        </button>
                        <button className="link" onClick={() => startEdit(item)}>
                          Edit
                        </button>
                        <button className="link" onClick={() => handleRemove(item)}>
                          Remove
                        </button>
                      </>
                    )}
                  </td>
                </tr>
                {historyFor === item.id && (
                  <tr className="chart-row">
                    <td colSpan={8} className="chart-cell">
                      {historyError && <p className="error">{historyError}</p>}
                      {historyPoints === null && !historyError && (
                        <p className="muted">Loading…</p>
                      )}
                      {historyPoints !== null && (
                        <PriceChart
                          points={historyPoints}
                          variant={item.variant}
                          onClose={() => setHistoryFor(null)}
                        />
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}