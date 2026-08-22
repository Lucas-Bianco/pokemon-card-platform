import { useEffect, useRef, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import { getCardLookup } from "../api/client";
import type { CardLookupItem } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";
import { staggerContainer, staggerItem } from "./motion";

// The Prices tab lookup (Task D): type a card name -> see matches with their
// latest market price. Honest prices; never $0.
//
// HONESTY (the whole feature):
// - `market` is null for cards with no market price -> the row shows "no market
//   price" (the em dash via formatMoney), NEVER a fabricated $0.00.
// - `source` + `source_updated_at` travel with every priced row so the UI can
//   say where a price came from and how stale it is. When absent, no staleness
//   line is rendered (never a fabricated source).
// - Empty states are distinct and honest: no query yet -> "Type a card name to
//   look up its price."; query with [] -> "No cards match."; error -> "Couldn't
//   load prices."
//
// Fetch goes through the typed client (`getCardLookup`), so a 422 from a
// short/whitespace query surfaces the backend's detail message via
// expectJsonOrDetail rather than a bare status.

export default function PriceLookup() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CardLookupItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce the text query (300ms); the timer ref is cleared on every change
  // so a fast typist doesn't fire a request per keystroke. Mirrors
  // SealedCatalog.tsx's debounce. An empty/whitespace query is NOT sent — the
  // backend requires a non-empty q, so we show the hint instead.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const trimmed = query.trim();
    if (!trimmed) {
      // No query yet -> honest empty state, no fetch.
      setResults(null);
      setLoading(false);
      setError(null);
      return;
    }
    const fire = () => {
      setLoading(true);
      setError(null);
      getCardLookup(trimmed, 20)
        .then((res) => setResults(res))
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Couldn't load prices."),
        )
        .finally(() => setLoading(false));
    };
    timer.current = setTimeout(fire, 300);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [query]);

  const trimmed = query.trim();

  return (
    <section className="deals price-lookup">
      <p className="muted small">
        Type a card name to see matches with their latest market price. A missing
        price is shown as “—” (no market price), never $0. Source + date travel
        with every priced row so you can see where a figure came from and how
        stale it is.
      </p>

      <div className="sealed-catalog-toolbar">
        <input
          type="search"
          className="deals-search"
          placeholder="Type a card name, e.g. 'Charizard' or 'Pikachu'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search cards by name"
          autoComplete="off"
        />
      </div>

      {error && <p className="error">Couldn't load prices.</p>}

      {loading && (
        <div className="skeleton skeleton-block" aria-label="Loading prices" />
      )}

      {!loading && !error && !trimmed && (
        <p className="muted">Type a card name to look up its price.</p>
      )}

      {!loading && !error && trimmed && results && results.length === 0 && (
        <p className="muted">No cards match.</p>
      )}

      {!loading && !error && results && results.length > 0 && (
        <PriceLookupBody results={results} />
      )}
    </section>
  );
}

function PriceLookupBody({ results }: { results: CardLookupItem[] }) {
  const reduced = useReducedMotion();
  return (
    <motion.ul
      className="deal-list price-lookup-list"
      variants={staggerContainer}
      initial={reduced ? "show" : "hidden"}
      animate="show"
    >
      {results.map((r) => (
        <PriceLookupCard key={r.card_id} result={r} />
      ))}
    </motion.ul>
  );
}

function PriceLookupCard({ result }: { result: CardLookupItem }) {
  const reduced = useReducedMotion();
  return (
    <motion.li
      className="deal-card price-lookup-card"
      variants={staggerItem}
      whileHover={reduced ? undefined : { y: -4 }}
      transition={{ duration: 0.16 }}
    >
      <div className="deal-card-head">
        <strong className="deal-title">{result.name}</strong>
        <span className="deal-price">{formatMoney(result.market)}</span>
      </div>
      <div className="deal-card-meta muted small">
        {result.set_name ? result.set_name : "Set unknown"}
        {result.number ? ` · #${result.number}` : ""}
        {result.rarity ? ` · ${result.rarity}` : ""}
      </div>

      <div className="deal-row price-lookup-market">
        <span className="deal-row-label">Market</span>
        <span className="deal-row-value">
          {result.market === null ? (
            <span className="muted small">no market price</span>
          ) : (
            formatMoney(result.market)
          )}
        </span>
      </div>

      {result.source && (
        <div className="deal-row price-lookup-source">
          <span className="deal-row-label">Source</span>
          <span className="deal-row-value muted small">
            {result.source}
            {result.source_updated_at
              ? ` · ${formatStaleness(result.source_updated_at)}`
              : ""}
          </span>
        </div>
      )}
    </motion.li>
  );
}