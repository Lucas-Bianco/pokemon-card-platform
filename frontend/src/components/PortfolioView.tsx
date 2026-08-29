import { Fragment, useCallback, useEffect, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import {
  getPriceHistory,
  getPortfolio,
  patchCollectionItem,
  removeFromCollection,
} from "../api/client";
import type { Portfolio, PortfolioItem, PricePoint } from "../api/types";
import { formatMoney } from "../lib/format";
import InsuranceValue from "./InsuranceValue";
import Diversification from "./Diversification";
import PortfolioHistoryChart from "./PortfolioHistoryChart";
import PriceFreshness from "./PriceFreshness";
import AcquisitionTimelineChart from "./AcquisitionTimelineChart";
import VaultExport from "./VaultExport";
import VaultImport from "./VaultImport";
import SoldLedger from "./SoldLedger";
import type { SoldPrefill } from "./SoldLedger";
import PriceChart from "./PriceChart";
import { staggerContainer, staggerItem } from "./motion";

interface Props {
  /** Vestigial after the app-chrome refactor: navigation back to the scan view
   *  is now owned by the persistent header toggle / bottom nav in App. Kept on
   *  the interface so existing callers and tests that pass it still type-check. */
  onBack?: () => void;
}

// Underscore-prefixed so noUnusedParameters permits the now-unused prop.
export default function PortfolioView(_props: Props) {
  const reduced = useReducedMotion();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The holding row whose "History" chart is open, plus its fetched points.
  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const [historyPoints, setHistoryPoints] = useState<PricePoint[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [saving, setSaving] = useState(false);
  // Prefill for the sold-lot "Log a sale" form, handed down from a holding
  // row's "Log sale" button. Cleared once the SoldLedger consumes it.
  const [salePrefill, setSalePrefill] = useState<SoldPrefill | null>(null);

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
  // A brand-new user still gets a summary back — with every figure at zero.
  // Rendering the valuation block off `summary` alone therefore asserts
  // "Market value $0.00 / Cost basis $0.00" for a collection that does not
  // exist: a fabricated valuation, which is exactly what this project forbids.
  // Dashboard.tsx gates the same KPIs behind a holdings check and shows an
  // honest empty state instead — mirror that. Note this suppresses the block
  // only when there is NOTHING to value; a GENUINE zero still renders, so
  // holdings that are all unpriced show $0.00 next to the "count as zero —
  // never guessed" caveat below, which is honest reporting, not a fabrication.
  const hasHoldings = (portfolio?.items?.length ?? 0) > 0;

  return (
    <section className="portfolio">
      {error && <p className="error">{error}</p>}

      {hasHoldings && summary && (
        <motion.div
          className="valuation"
          variants={staggerContainer}
          initial={reduced ? "show" : "hidden"}
          animate="show"
        >
          <motion.div
            variants={staggerItem}
            whileHover={reduced ? undefined : { y: -4 }}
            whileTap={reduced ? undefined : { scale: 0.985 }}
            transition={{ duration: 0.16 }}
          >
            <span className="label">Market value</span>
            <strong>{formatMoney(summary.market_value)}</strong>
          </motion.div>
          <motion.div
            variants={staggerItem}
            whileHover={reduced ? undefined : { y: -4 }}
            whileTap={reduced ? undefined : { scale: 0.985 }}
            transition={{ duration: 0.16 }}
          >
            <span className="label">Cost basis</span>
            <strong>{formatMoney(summary.cost_basis)}</strong>
          </motion.div>
          <motion.div
            variants={staggerItem}
            whileHover={reduced ? undefined : { y: -4 }}
            whileTap={reduced ? undefined : { scale: 0.985 }}
            transition={{ duration: 0.16 }}
          >
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
          </motion.div>
          <motion.div
            variants={staggerItem}
            whileHover={reduced ? undefined : { y: -4 }}
            whileTap={reduced ? undefined : { scale: 0.985 }}
            transition={{ duration: 0.16 }}
          >
            <span className="label">Priced / unpriced</span>
            <strong>
              {summary.priced_items} / {summary.unpriced_items}
            </strong>
          </motion.div>
        </motion.div>
      )}

      {hasHoldings && summary && summary.cost_basis === 0 && (
        <p className="muted small">
          No purchase prices recorded yet, so profit/loss is unknown. Enter what you paid when you
          add a card (or edit a holding below) and it will start tracking.
        </p>
      )}

      {hasHoldings && summary && summary.unpriced_items > 0 && (
        <p className="muted small">
          {summary.unpriced_items} item{summary.unpriced_items === 1 ? "" : "s"} have no market
          price yet and count as zero — never guessed.
        </p>
      )}

      {/* Sections reordered for the key-mode Vault: the holdings table is the
          primary content a collector acts on, so it sits right under the
          headline KPIs and the at-a-glance allocation / movers. The action
          tools (export / import / sold-ledger) and the deep read-only
          analytics panels follow at the bottom of this view — see the Tools
          and Analytics sections after the table. */}

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

      {portfolio === null && !error && (
        <div className="skeleton skeleton-block" aria-label="Loading portfolio" />
      )}

      {portfolio !== null && portfolio.items.length === 0 && (
        <p className="muted">Nothing here yet. Scan a card and tap “add to collection”.</p>
      )}

      {portfolio !== null && portfolio.items.length > 0 && (
        <div className="portfolio-table-wrap">
          <table className="portfolio-table">
            <thead>
              <tr>
                <th>Qty</th>
                <th>Card</th>
                <th className="col-variant">Variant</th>
                <th className="col-set">Set</th>
                <th>Paid</th>
                <th>Market</th>
                <th>Unrealised</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.items.map((item) => (
                <Fragment key={item.id}>
                  <tr className="holding-row">
                    <td data-label="Qty">×{item.quantity}</td>
                    <td data-label="Card" className="name">
                      {item.card_name}
                    </td>
                    <td data-label="Variant" className="col-variant">
                      {item.variant}
                    </td>
                    <td data-label="Set" className="muted col-set">
                      {item.set_name}
                    </td>
                    <td data-label="Paid">
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
                    <td data-label="Market">
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
                    <td data-label="Unrealised">
                      {item.unrealized === null ? (
                        <span className="unknown">—</span>
                      ) : (
                        <strong className={item.unrealized >= 0 ? "up" : "down"}>
                          {item.unrealized >= 0 ? "+" : "−"}
                          {formatMoney(Math.abs(item.unrealized))}
                        </strong>
                      )}
                    </td>
                    <td data-label="Actions" className="actions">
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
                          <button
                            className="link"
                            onClick={() =>
                              setSalePrefill({
                                card_id: item.card_id,
                                variant: item.variant,
                                card_name: item.card_name,
                                acquired_price: item.acquired_price,
                              })
                            }
                          >
                            Log sale
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
                          <div className="skeleton skeleton-block" aria-label="Loading price history" />
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
        </div>
      )}

      {/* Tools — act on the collection: export, import, and the sold-lot
          ledger. Kept open (not collapsible) because a holding row's "Log
          sale" button pre-fills the sold-ledger form and scrolls to it; a
          closed container would hide that. */}
      <section className="vault-section vault-tools" aria-label="Vault tools">
        <h2>Tools</h2>
        {hasHoldings && <VaultExport />}
        <VaultImport />
        <SoldLedger prefill={salePrefill} onPrefillConsumed={() => setSalePrefill(null)} />
      </section>

      {/* Read-only analytics — insurance value, diversification, value-over-
          time, price freshness, acquisition timeline. Collapsible so a
          collector who just wants their holdings can fold the wall away;
          default open so the data is visible without an extra tap. */}
      {hasHoldings && (
        <details className="vault-section vault-analytics" open>
          <summary>Analytics</summary>
          <InsuranceValue />
          <Diversification />
          <PortfolioHistoryChart />
          <PriceFreshness />
          <AcquisitionTimelineChart />
        </details>
      )}
    </section>
  );
}