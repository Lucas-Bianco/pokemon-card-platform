import { useEffect, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import {
  deleteSealedPurchase,
  getSealedLedger,
  logSealedPurchase,
  syncSealedLedger,
  valuateSealedLedger,
} from "../api/client";
import type { SealedLedgerEntry, SealedLedgerResponse } from "../api/types";
import { formatMoney } from "../lib/format";
import { relativeTime } from "../lib/time";
import { staggerContainer, staggerItem } from "./motion";
import { useToast } from "./Toast";

// The Sealed-ledger screen: a form to log sealed boxes/packs you bought + a
// list of purchases with live profit vs the eBay sold-comps median. Sealed
// products are query-keyed (like sealed deals) — the query IS the product.
// Every market figure shows its source + a relative "valued <relative>"
// staleness; every missing value renders an em dash via formatMoney, never
// $0.00 (the project's sacred convention). The footer caveat rides every card
// — profit is gross of selling fees, indicative as of the valuation timestamp.
//
// Visual language: reuses the existing `.deal-*` classes from the Deals screen
// (card surface+border, row label alignment, chip pill, caveat margin) so the
// Ledger tab is visually consistent with the Deals/Sealed tabs. The only new
// CSS is a small `.ledger-form` grid + `.ledger-input` / `.ledger-profit` /
// `.ledger-delete` rules (see styles.css).
export default function SealedLedger() {
  const { toast } = useToast();
  const [data, setData] = useState<SealedLedgerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // log form
  const [query, setQuery] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [cost, setCost] = useState("");
  const [ptype, setPtype] = useState("");
  const [source, setSource] = useState("");
  const [logging, setLogging] = useState(false);

  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await getSealedLedger());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the ledger.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function logPurchase(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    const c = parseFloat(cost);
    const n = parseInt(quantity, 10);
    if (q.length < 2 || !Number.isFinite(c) || c < 0 || !Number.isFinite(n) || n < 1) {
      setError("Enter a product, a cost per unit (>=0), and a quantity (>=1).");
      return;
    }
    setLogging(true);
    setError(null);
    setNotice(null);
    try {
      await logSealedPurchase({
        query: q,
        quantity: n,
        cost_per_unit: c,
        product_type: ptype || null,
        source: source || null,
      });
      setQuery("");
      setCost("");
      setQuantity("1");
      setPtype("");
      setSource("");
      setNotice("Purchase logged.");
      toast("Purchase logged", "success");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't log the purchase.");
    } finally {
      setLogging(false);
    }
  }

  async function refresh() {
    setRefreshing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await valuateSealedLedger();
      if (res.skipped_no_key) {
        setNotice("Set CARDPLATFORM_LISTINGS_API_KEY to value purchases (fetch sold comps).");
        toast("eBay key missing — valuations skipped", "warn");
      } else {
        setNotice(`Valued ${res.valued} purchase(s); ${res.skipped_no_comps} had no sold comps.`);
        if (res.valued > 0) toast("Valuations refreshed", "success");
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't refresh valuations.");
    } finally {
      setRefreshing(false);
    }
  }

  async function sync() {
    setSyncing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await syncSealedLedger();
      if (!res.synced && res.reason === "not_configured") {
        setNotice("Google Sheets not configured — place an OAuth client secret at data/credentials.json and set CARDPLATFORM_GOOGLE_SHEET_ID, then sync again.");
        toast("Sheets not configured", "warn");
      } else if (!res.synced) {
        setNotice(`Sync did not complete: ${res.reason ?? "unknown"}.`);
      } else {
        setNotice(`Synced ${res.rows} row(s) to Google Sheets.`);
        toast("Sheet synced", "success");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't sync to Google Sheets.");
    } finally {
      setSyncing(false);
    }
  }

  async function remove(id: number) {
    try {
      await deleteSealedPurchase(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete the purchase.");
    }
  }

  return (
    <section className="deals">
      <p className="muted small">Log sealed boxes/packs you bought; track live profit vs the eBay sold-comps median.</p>

      <form className="ledger-form" onSubmit={logPurchase}>
        <input
          name="ledger-query"
          className="deals-search"
          placeholder="Product, e.g. 'scarlet violet booster box'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Product"
          autoComplete="off"
        />
        <input
          name="ledger-cost"
          className="ledger-input"
          type="number"
          step="0.01"
          min="0"
          placeholder="Cost/unit $"
          value={cost}
          onChange={(e) => setCost(e.target.value)}
          aria-label="Cost per unit"
        />
        <input
          name="ledger-qty"
          className="ledger-input"
          type="number"
          min="1"
          step="1"
          placeholder="Qty"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          aria-label="Quantity"
        />
        <select
          name="ledger-type"
          className="ledger-input"
          value={ptype}
          onChange={(e) => setPtype(e.target.value)}
          aria-label="Product type"
        >
          <option value="">Type…</option>
          <option value="booster_box">Booster box</option>
          <option value="etb">ETB</option>
          <option value="pack">Pack</option>
          <option value="collection_box">Collection box</option>
          <option value="other">Other</option>
        </select>
        <input
          name="ledger-source"
          className="ledger-input"
          placeholder="Bought from (optional)"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          aria-label="Source"
          autoComplete="off"
        />
        <button type="submit" className="sealed-deals-btn" disabled={logging}>
          {logging ? "Logging…" : "Log purchase"}
        </button>
      </form>

      <div className="deals-toolbar">
        <button type="button" className="sealed-deals-btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh valuations"}
        </button>
        <button type="button" className="sealed-deals-btn" onClick={sync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync to Google Sheets"}
        </button>
      </div>

      {notice && <p className="muted small">{notice}</p>}
      {error && <p className="error">{error}</p>}
      {loading && <div className="skeleton skeleton-block" aria-label="Loading ledger" />}
      {data && <LedgerBody entries={data.purchases} onRemove={remove} />}
    </section>
  );
}

function LedgerBody({
  entries,
  onRemove,
}: {
  entries: SealedLedgerEntry[];
  onRemove: (id: number) => void;
}) {
  const reduced = useReducedMotion();
  if (entries.length === 0) {
    return <p className="muted">No purchases logged yet — log one above.</p>;
  }
  return (
    <motion.ul
      className="deal-list"
      variants={staggerContainer}
      initial={reduced ? "show" : "hidden"}
      animate="show"
    >
      {entries.map((e) => {
        const profitClass =
          e.profit === null ? "" : e.profit >= 0 ? "ledger-profit pos" : "ledger-profit neg";
        return (
          <motion.li
            className="deal-card"
            key={e.id}
            variants={staggerItem}
            whileHover={reduced ? undefined : { y: -4 }}
            whileTap={reduced ? undefined : { scale: 0.985 }}
            transition={{ duration: 0.16 }}
          >
            <div className="deal-card-head">
              <span className="deal-title">
                <strong>
                  {e.quantity}× {e.query}
                </strong>
              </span>
              <span className="deal-price">{formatMoney(e.total_current_value)}</span>
            </div>
            <div className="deal-card-meta muted small">
              {e.product_type ?? "sealed"}
            </div>
            <div className="deal-row">
              <span className="deal-row-label">Cost</span>
              <span className="deal-row-value">
                {formatMoney(e.total_cost)} ({formatMoney(e.cost_per_unit)}/u)
              </span>
            </div>
            <div className="deal-row">
              <span className="deal-row-label">Market</span>
              <span className="deal-row-value">
                {e.valued ? `${formatMoney(e.value_per_unit)}/u` : "not yet valued — click Refresh"}
              </span>
            </div>
            <div className="deal-row">
              <span className="deal-row-label">Profit</span>
              <span className={`deal-row-value ${profitClass}`}>
                {e.profit === null
                  ? "—"
                  : `${formatMoney(e.profit)} (${e.profit_pct === null ? "—" : (e.profit_pct * 100).toFixed(0) + "%"})`}
              </span>
            </div>
            {e.valued && e.market_fetched_at && (
              <div className="deal-row">
                <span className="deal-row-label">Valued</span>
                <span className="deal-row-value">
                  {relativeTime(e.market_fetched_at)} · {e.market_source}
                </span>
              </div>
            )}
            {e.source && (
              <div className="deal-row">
                <span className="deal-row-label">Bought from</span>
                <span className="deal-row-value">{e.source}</span>
              </div>
            )}
            {e.notes && (
              <div className="deal-row">
                <span className="deal-row-label">Notes</span>
                <span className="deal-row-value">{e.notes}</span>
              </div>
            )}
            <div className="deal-chips">
              <span className="deal-caveat muted small">
                Gross edge — selling fees not subtracted; profit is indicative (as of valuation).
              </span>
              <button type="button" className="ledger-delete" onClick={() => onRemove(e.id)}>
                Delete
              </button>
            </div>
          </motion.li>
        );
      })}
    </motion.ul>
  );
}