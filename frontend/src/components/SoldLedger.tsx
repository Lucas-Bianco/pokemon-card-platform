// Sold-lot ledger (Row 29) — realized gains / the disposal counterpart to the
// vault. A permanent, append-only record of cards you've *sold*. Each lot
// carries its sale price, optional fee, and the cost basis *snapshotted at
// sale time*, so realized P/L is fixed and never recomputed against a holding
// you may have since edited or deleted.
//
// Honest: `proceeds` is always known (a sale has a price); `cost_basis` /
// `realized` are null when no cost basis was recorded at sale time — never a
// fabricated $0. The summary's `total_realized` is over the cost-known subset
// only; lots without a cost basis are counted in `lots_without_cost` and
// excluded from realized, never $0. Mounted unconditionally (you can sell your
// last card), and a holding row's "Log sale" button pre-fills the form via the
// `prefill` prop.
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { addSoldLot, getSoldLots, getSoldSummary, removeSoldLot } from "../api/client";
import type { SoldLot, SoldSummary } from "../api/types";
import { formatMoney } from "../lib/format";

export interface SoldPrefill {
  card_id: string;
  variant: string;
  card_name: string;
  acquired_price: number | null;
}

interface Props {
  prefill?: SoldPrefill | null;
  onPrefillConsumed?: () => void;
}

const EMPTY_FORM = {
  card_id: "",
  variant: "normal",
  quantity: "1",
  sale_price: "",
  sale_fee: "",
  acquired_price: "",
  source: "",
  notes: "",
  sold_at: "",
};

function toIsoDate(value: string): string | null {
  // The date input yields YYYY-MM-DD; send an aware UTC midnight so the
  // backend's UtcDateTime decorator (which rejects naive datetimes) accepts it.
  if (!value) return null;
  return `${value}T00:00:00Z`;
}

function parseNum(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export default function SoldLedger({ prefill, onPrefillConsumed }: Props) {
  const [lots, setLots] = useState<SoldLot[] | null>(null);
  const [summary, setSummary] = useState<SoldSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const formRef = useRef<HTMLElement | null>(null);
  const cardInputId = useId();

  const load = useCallback(async () => {
    setError(null);
    try {
      const [items, summ] = await Promise.all([getSoldLots(), getSoldSummary()]);
      setLots(items);
      setSummary(summ);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the sold-lots ledger.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // When a holding row hands us a prefill, populate the form and focus it.
  useEffect(() => {
    if (!prefill) return;
    setForm({
      ...EMPTY_FORM,
      card_id: prefill.card_id,
      variant: prefill.variant,
      quantity: "1",
      acquired_price:
        prefill.acquired_price !== null ? String(prefill.acquired_price) : "",
    });
    setFormOpen(true);
    setFormError(null);
    // Focus after render.
    const t = window.setTimeout(() => {
      const el = formRef.current;
      // jsdom lacks scrollIntoView; guard so tests don't throw.
      if (el && typeof el.scrollIntoView === "function") {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      document.getElementById(cardInputId)?.focus();
    }, 0);
    onPrefillConsumed?.();
    return () => window.clearTimeout(t);
  }, [prefill, cardInputId, onPrefillConsumed]);

  const setField = (key: keyof typeof form, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const salePrice = parseNum(form.sale_price);
    if (salePrice === null || salePrice < 0) {
      setFormError("Enter a sale price (0 or more).");
      return;
    }
    const qty = parseNum(form.quantity);
    if (qty === null || qty < 1) {
      setFormError("Quantity must be 1 or more.");
      return;
    }
    if (form.card_id.trim() === "") {
      setFormError("Enter a card id.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await addSoldLot({
        card_id: form.card_id.trim(),
        variant: form.variant.trim() || "normal",
        quantity: qty,
        sale_price: salePrice,
        sale_fee: parseNum(form.sale_fee),
        acquired_price: parseNum(form.acquired_price),
        sold_at: toIsoDate(form.sold_at),
        source: form.source.trim() || null,
        notes: form.notes.trim() || null,
      });
      setForm({ ...EMPTY_FORM });
      setFormOpen(false);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not record the sale.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(lot: SoldLot) {
    try {
      await removeSoldLot(lot.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the sold lot.");
    }
  }

  const loading = lots === null;

  return (
    <section className="sold-ledger" aria-label="Sold-lot ledger">
      <h3>Sold lots — realized gains</h3>
      <p className="muted small">
        A permanent record of cards you've sold. Realized P/L is (sale price − fee) × quantity minus
        what you paid (snapshotted at sale time) — computed only over lots with a recorded purchase
        price; lots without one are counted but excluded from realized, never $0.
      </p>

      {error && <p className="error">{error}</p>}

      {summary && summary.lot_count > 0 && (
        <div className="sold-summary">
          <div>
            <span className="label">Proceeds</span>
            <strong>{formatMoney(summary.total_proceeds)}</strong>
          </div>
          <div>
            <span className="label">Realized</span>
            {summary.lots_with_cost === 0 ? (
              <strong className="unknown">—</strong>
            ) : (
              <strong className={summary.total_realized >= 0 ? "up" : "down"}>
                {summary.total_realized >= 0 ? "+" : "−"}
                {formatMoney(Math.abs(summary.total_realized))}
              </strong>
            )}
          </div>
          <div>
            <span className="label">Winners / losers</span>
            <strong>
              {summary.winners} / {summary.losers}
            </strong>
          </div>
          <div>
            <span className="label">Lots</span>
            <strong>
              {summary.lot_count}
              {summary.lots_without_cost > 0 && (
                <span className="muted small"> ({summary.lots_without_cost} no cost)</span>
              )}
            </strong>
          </div>
        </div>
      )}

      <div className="sold-form-toggle">
        {!formOpen ? (
          <button type="button" className="btn btn-secondary" onClick={() => setFormOpen(true)}>
            Log a sale
          </button>
        ) : (
          <form ref={formRef as unknown as React.RefObject<HTMLFormElement>} className="sold-form" onSubmit={handleSubmit}>
            <h4>Log a sale</h4>
            <label>
              Card id
              <input
                id={cardInputId}
                value={form.card_id}
                onChange={(e) => setField("card_id", e.target.value)}
                placeholder="e.g. base1-4"
                aria-label="Card id"
              />
            </label>
            <label>
              Variant
              <input
                value={form.variant}
                onChange={(e) => setField("variant", e.target.value)}
                placeholder="normal"
                aria-label="Variant"
              />
            </label>
            <label>
              Quantity
              <input
                type="number"
                min="1"
                step="1"
                value={form.quantity}
                onChange={(e) => setField("quantity", e.target.value)}
                aria-label="Quantity"
              />
            </label>
            <label>
              Sale price
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.sale_price}
                onChange={(e) => setField("sale_price", e.target.value)}
                placeholder="0.00"
                aria-label="Sale price"
              />
            </label>
            <label>
              Sale fee (optional)
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.sale_fee}
                onChange={(e) => setField("sale_fee", e.target.value)}
                placeholder="0.00"
                aria-label="Sale fee"
              />
            </label>
            <label>
              Cost basis / each (optional)
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.acquired_price}
                onChange={(e) => setField("acquired_price", e.target.value)}
                placeholder="what you paid"
                aria-label="Cost basis per unit"
              />
            </label>
            <label>
              Sold on (optional)
              <input
                type="date"
                value={form.sold_at}
                onChange={(e) => setField("sold_at", e.target.value)}
                aria-label="Sold on"
              />
            </label>
            <label>
              Source (optional)
              <input
                value={form.source}
                onChange={(e) => setField("source", e.target.value)}
                placeholder="eBay, TCGplayer…"
                aria-label="Source"
              />
            </label>
            <label className="sold-form-notes">
              Notes (optional)
              <textarea
                value={form.notes}
                onChange={(e) => setField("notes", e.target.value)}
                rows={2}
                aria-label="Notes"
              />
            </label>
            {formError && <p className="error small">{formError}</p>}
            <div className="sold-form-actions">
              <button type="submit" className="btn" disabled={submitting}>
                {submitting ? "Saving…" : "Save sale"}
              </button>
              <button
                type="button"
                className="link"
                onClick={() => {
                  setFormOpen(false);
                  setForm({ ...EMPTY_FORM });
                  setFormError(null);
                }}
              >
                cancel
              </button>
            </div>
          </form>
        )}
      </div>

      {loading && !error && <div className="skeleton skeleton-block" aria-label="Loading sold lots" />}

      {lots !== null && lots.length === 0 && (
        <p className="muted">No sales recorded yet. Tap “Log a sale” to record one.</p>
      )}

      {lots !== null && lots.length > 0 && (
        <div className="portfolio-table-wrap">
          <table className="portfolio-table sold-table">
            <thead>
              <tr>
                <th>Qty</th>
                <th>Card</th>
                <th className="col-variant">Variant</th>
                <th className="col-set">Set</th>
                <th>Sale</th>
                <th>Proceeds</th>
                <th>Realized</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {lots.map((lot) => (
                <tr key={lot.id} className="holding-row">
                  <td data-label="Qty">×{lot.quantity}</td>
                  <td data-label="Card" className="name">
                    {lot.card_name}
                    {lot.source && <span className="muted small"> · {lot.source}</span>}
                  </td>
                  <td data-label="Variant" className="col-variant">
                    {lot.variant}
                  </td>
                  <td data-label="Set" className="muted col-set">
                    {lot.set_name}
                  </td>
                  <td data-label="Sale">{formatMoney(lot.sale_price)}</td>
                  <td data-label="Proceeds">{formatMoney(lot.proceeds)}</td>
                  <td data-label="Realized">
                    {lot.realized === null ? (
                      <span className="unknown">—</span>
                    ) : (
                      <strong className={lot.realized >= 0 ? "up" : "down"}>
                        {lot.realized >= 0 ? "+" : "−"}
                        {formatMoney(Math.abs(lot.realized))}
                      </strong>
                    )}
                  </td>
                  <td data-label="Actions" className="actions">
                    <button className="link" onClick={() => handleRemove(lot)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}