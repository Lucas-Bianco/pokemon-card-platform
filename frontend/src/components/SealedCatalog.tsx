import { useEffect, useRef, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import {
  getSealedProductMarket,
  getSealedProducts,
  logSealedFromCatalog,
} from "../api/client";
import type {
  SealedPrintStatus,
  SealedProduct,
  SealedProductMarket,
  SealedProductType,
  SealedProductsResponse,
} from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";
import { useToast } from "./Toast";
import { staggerContainer, staggerItem } from "./motion";

// The Catalog tab (Phase A, roadmap row 09): a browsable, searchable reference
// catalog of every sealed Pokémon product that contains card packs — booster
// packs, booster boxes, ETBs, collection boxes, tins, premium bundles — Base era
// → newest, with an honest MSRP and an in-print / out-of-print / unknown tag.
//
// Phase B (scan-to-log) + Phase C (MSRP vs market) mount inline on each card:
//   - "Log to ledger" expands a mini-form (quantity + cost + optional source)
//     that POSTs /sealed/ledger/from-catalog by slug and toasts the result.
//   - "vs market" expands a panel that GETs /sealed/products/{slug}/market and
//     shows the curated MSRP against the live sold-comps median, with the SAME
//     honest unavailable/empty flags as the sold-comps tab.
//
// HONESTY (the whole feature):
// - The seed is curated + in-repo, NOT "magic auto-update" — there is no official
//   sealed-product API. A future semi-automated community sync (Pokellector /
//   TCGplayer) with manual review is a documented follow-up. The toolbar says so.
// - `msrp` is null for products with no official US MSRP (booster boxes, premiums)
//   → the card shows "no MSRP" via formatMoney's em dash, NEVER a fabricated $0.
// - `market_median` is null when there are no comps (or no key) → the panel shows
//   "no recent sales" / "set a listings key", NEVER a fabricated $0. `delta` is
//   null unless BOTH msrp and market_median are real numbers.
// - `print_status` is a best-effort tag, never a guarantee (products re-enter print).
//
// Visual language: reuses the `.deal-*` card idiom (surface + chip pill) for
// consistency with the Deals/Sealed tabs; only additive `.sealed-catalog-*` classes
// are introduced (toolbar, chip variants, caveat, log form, vs-market panel).

const TYPE_OPTIONS: { value: "" | SealedProductType; label: string }[] = [
  { value: "", label: "All types" },
  { value: "booster_pack", label: "Booster packs" },
  { value: "booster_box", label: "Booster boxes" },
  { value: "etb", label: "Elite Trainer Boxes" },
  { value: "collection_box", label: "Collection boxes" },
  { value: "tin", label: "Tins" },
  { value: "premium_bundle", label: "Premium bundles" },
  { value: "other", label: "Other" },
];

const STATUS_OPTIONS: { value: "" | SealedPrintStatus; label: string }[] = [
  { value: "", label: "All print status" },
  { value: "in_print", label: "In print" },
  { value: "out_of_print", label: "Out of print" },
  { value: "unknown", label: "Unknown" },
];

const PRINT_LABEL: Record<SealedPrintStatus, string> = {
  in_print: "In print",
  out_of_print: "Out of print",
  unknown: "Print unknown",
};

const TYPE_LABEL: Record<SealedProductType, string> = {
  booster_pack: "Booster pack",
  booster_box: "Booster box",
  etb: "ETB",
  collection_box: "Collection box",
  tin: "Tin",
  premium_bundle: "Premium bundle",
  other: "Other",
};

function releasedYear(releasedAt: string | null): string | null {
  if (!releasedAt) return null;
  const m = releasedAt.match(/^(\d{4})/);
  return m ? m[1] : null;
}

export default function SealedCatalog() {
  const [query, setQuery] = useState("");
  const [productType, setProductType] = useState<"" | SealedProductType>("");
  const [printStatus, setPrintStatus] = useState<"" | SealedPrintStatus>("");
  const [data, setData] = useState<SealedProductsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounce the text query (300ms); selects fetch immediately. The timer ref is
  // cleared on every change so a fast typist doesn't fire a request per keystroke.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const fire = () => {
      setLoading(true);
      setError(null);
      getSealedProducts(
        query.trim() || undefined,
        productType || undefined,
        printStatus || undefined,
        200,
      )
        .then((res) => setData(res))
        .catch((err) => setError(err instanceof Error ? err.message : "Couldn't load the catalog."))
        .finally(() => setLoading(false));
    };
    timer.current = setTimeout(fire, 300);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [query, productType, printStatus]);

  return (
    <section className="deals sealed-catalog">
      <p className="muted small">
        Browse every sealed Pokémon product with card packs — booster packs, boxes, ETBs,
        tins, bundles — Base era to newest. MSRP is shown where an official US retail price
        exists; “—” means no public MSRP (booster boxes, premiums), never $0. Print status
        is a best-effort tag. Curated seed — a semi-automated community sync is a planned
        follow-up, not magic auto-update. Log a buy or compare MSRP to the live market on
        any card.
      </p>

      <div className="sealed-catalog-toolbar">
        <input
          type="search"
          className="deals-search"
          placeholder="Search by name or era, e.g. 'Scarlet & Violet' or 'ETB'"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the sealed catalog"
          autoComplete="off"
        />
        <select
          className="sealed-catalog-select"
          value={productType}
          onChange={(e) => setProductType(e.target.value as "" | SealedProductType)}
          aria-label="Filter by product type"
        >
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          className="sealed-catalog-select"
          value={printStatus}
          onChange={(e) => setPrintStatus(e.target.value as "" | SealedPrintStatus)}
          aria-label="Filter by print status"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error">{error}</p>}

      {loading && (
        <div className="skeleton skeleton-block" aria-label="Loading sealed catalog" />
      )}

      {!loading && data && <SealedCatalogBody data={data} products={data.products} />}
    </section>
  );
}

function SealedCatalogBody({
  data,
  products,
}: {
  data: SealedProductsResponse;
  products: SealedProduct[];
}) {
  const reduced = useReducedMotion();
  // HONEST empty states — a missing seed and a filtered-but-empty search carry
  // different copy; both are honest, never a fabricated row.
  if (products.length === 0) {
    const filtered = data.product_type || data.print_status;
    return (
      <p className="muted">
        {filtered
          ? "No products match these filters."
          : "No products seeded yet."}
      </p>
    );
  }

  return (
    <>
      <p className="muted small sealed-catalog-count">
        {data.count} product{data.count === 1 ? "" : "s"}
      </p>
      <motion.ul
        className="deal-list sealed-catalog-list"
        variants={staggerContainer}
        initial={reduced ? "show" : "hidden"}
        animate="show"
      >
        {products.map((p) => (
          <SealedCatalogCard key={p.slug} product={p} />
        ))}
      </motion.ul>
      <p className="deal-caveat muted small">
        MSRP is an approximate US retail price where one is well-known, not an official
        figure where ambiguous. Print status is best-effort — products re-enter print.
        Market median is the median of recent eBay sold comps — actual transactions,
        not a listed estimate.
      </p>
    </>
  );
}

function SealedCatalogCard({ product }: { product: SealedProduct }) {
  const reduced = useReducedMotion();
  const year = releasedYear(product.released_at);
  // Each card owns its own expand state for the two inline actions, so opening
  // "vs market" on one card doesn't open it on every card.
  const [openMarket, setOpenMarket] = useState(false);
  const [openLog, setOpenLog] = useState(false);

  return (
    <motion.li
      className="deal-card sealed-catalog-card"
      variants={staggerItem}
      whileHover={reduced ? undefined : { y: -4 }}
      transition={{ duration: 0.16 }}
    >
      <div className="deal-card-head">
        <strong className="deal-title">{product.name}</strong>
        <span className="deal-price">{formatMoney(product.msrp)}</span>
      </div>
      <div className="deal-card-meta muted small">
        {product.era ? product.era : "Era unknown"}
        {year ? ` · ${year}` : ""}
      </div>

      <div className="deal-chips sealed-catalog-chips">
        <span className={`deal-chip sealed-catalog-type type-${product.product_type}`}>
          {TYPE_LABEL[product.product_type]}
        </span>
        <span className={`deal-chip sealed-catalog-print print-${product.print_status}`}>
          {PRINT_LABEL[product.print_status]}
        </span>
      </div>

      <div className="deal-row sealed-catalog-msrp">
        <span className="deal-row-label">MSRP</span>
        <span className="deal-row-value">
          {product.msrp === null ? (
            <span className="muted small">no MSRP</span>
          ) : (
            <>
              {formatMoney(product.msrp)}
              <span className="muted small"> {product.msrp_currency}</span>
            </>
          )}
        </span>
      </div>

      {product.source_url && (
        <a
          className="deal-title sealed-catalog-source"
          href={product.source_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Source
        </a>
      )}

      <div className="sealed-catalog-actions">
        <button
          type="button"
          className="sealed-catalog-action"
          aria-expanded={openLog}
          aria-controls={`log-${product.slug}`}
          onClick={() => setOpenLog((v) => !v)}
        >
          {openLog ? "Close" : "Log to ledger"}
        </button>
        <button
          type="button"
          className="sealed-catalog-action"
          aria-expanded={openMarket}
          aria-controls={`market-${product.slug}`}
          onClick={() => setOpenMarket((v) => !v)}
        >
          {openMarket ? "Close" : "vs market"}
        </button>
      </div>

      {openLog && <SealedCatalogLogForm product={product} />}
      {openMarket && <SealedCatalogMarketPanel product={product} />}
    </motion.li>
  );
}

// Phase B — inline "log this buy to the ledger" form. The product's name +
// product_type are resolved server-side from the slug, so the form only collects
// the purchase facts: quantity (default 1), cost (required), optional source.
// On submit it POSTs /sealed/ledger/from-catalog and toasts the honest result:
// success carries the logged quantity + name; a 404/422 surfaces the backend's
// detail (the client throws with that message). The form never fabricates a
// cost — the input is required and the button is disabled until it's filled.
function SealedCatalogLogForm({ product }: { product: SealedProduct }) {
  const { toast } = useToast();
  const [quantity, setQuantity] = useState("1");
  const [cost, setCost] = useState("");
  const [source, setSource] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const costNum = parseFloat(cost);
  const qtyNum = parseInt(quantity, 10);
  const canSubmit =
    !submitting &&
    Number.isFinite(costNum) &&
    costNum >= 0 &&
    Number.isInteger(qtyNum) &&
    qtyNum >= 1;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await logSealedFromCatalog({
        slug: product.slug,
        quantity: qtyNum,
        cost_per_unit: costNum,
        source: source.trim() || null,
      });
      toast(`Logged ${qtyNum} × ${product.name} to the ledger.`, "success");
      setCost("");
      setSource("");
      setQuantity("1");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Couldn't log the purchase.",
        "warn",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      id={`log-${product.slug}`}
      className="sealed-catalog-log-form"
      onSubmit={onSubmit}
    >
      <label className="sealed-catalog-field">
        <span>Quantity</span>
        <input
          type="number"
          min={1}
          step={1}
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          aria-label={`Quantity of ${product.name}`}
        />
      </label>
      <label className="sealed-catalog-field">
        <span>Cost each</span>
        <input
          type="number"
          min={0}
          step="0.01"
          value={cost}
          onChange={(e) => setCost(e.target.value)}
          aria-label={`Cost per unit for ${product.name}`}
          placeholder="0.00"
          required
        />
      </label>
      <label className="sealed-catalog-field">
        <span>Source (optional)</span>
        <input
          type="text"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          aria-label={`Source for ${product.name}`}
          placeholder="Pokémon Center, eBay, …"
        />
      </label>
      <button type="submit" className="sealed-catalog-submit" disabled={!canSubmit}>
        {submitting ? "Logging…" : "Log buy"}
      </button>
    </form>
  );
}

// Phase C — inline "MSRP vs market" panel. Fetches the live sold-comps median
// for this product on expand and shows it against the curated MSRP. Honest
// states mirror the sold-comps tab exactly: `unavailable` (no listings key) →
// "set a listings key"; `empty` (key set, 0 comps) → "no recent sold comps";
// `market_median` null in both → no fabricated $0. `delta` is null unless BOTH
// msrp and market_median are real. The panel never raises out of a provider
// failure — the backend degrades to [] and `empty` is true.
function SealedCatalogMarketPanel({ product }: { product: SealedProduct }) {
  const [market, setMarket] = useState<SealedProductMarket | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSealedProductMarket(product.slug)
      .then((res) => {
        if (!cancelled) setMarket(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't load the market.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [product.slug]);

  if (loading) {
    return (
      <div
        id={`market-${product.slug}`}
        className="sealed-catalog-market"
        aria-label={`Loading market for ${product.name}`}
      >
        <div className="skeleton skeleton-block" />
      </div>
    );
  }

  if (error) {
    return (
      <div id={`market-${product.slug}`} className="sealed-catalog-market">
        <p className="error small">{error}</p>
      </div>
    );
  }

  if (!market) return null;

  return (
    <div id={`market-${product.slug}`} className="sealed-catalog-market">
      <div className="deal-row sealed-catalog-market-msrp">
        <span className="deal-row-label">MSRP</span>
        <span className="deal-row-value">
          {market.msrp === null ? (
            <span className="muted small">no MSRP</span>
          ) : (
            <>
              {formatMoney(market.msrp)}
              <span className="muted small"> {market.msrp_currency}</span>
            </>
          )}
        </span>
      </div>

      <div className="deal-row sealed-catalog-market-median">
        <span className="deal-row-label">Market median</span>
        <span className="deal-row-value">
          {market.unavailable ? (
            <span className="muted small">set a listings key to see this</span>
          ) : market.empty || market.market_median === null ? (
            <span className="muted small">no recent sold comps</span>
          ) : (
            formatMoney(market.market_median)
          )}
        </span>
      </div>

      <div className="deal-row sealed-catalog-market-delta">
        <span className="deal-row-label">MSRP − market</span>
        <span className="deal-row-value">
          {market.delta === null ? (
            <span className="muted small">—</span>
          ) : (
            <span className={market.delta >= 0 ? "deal-delta-over" : "deal-delta-under"}>
              {market.delta >= 0 ? "+" : ""}
              {formatMoney(market.delta)}
            </span>
          )}
        </span>
      </div>

      <div className="deal-row sealed-catalog-market-comps">
        <span className="deal-row-label">Sold comps</span>
        <span className="deal-row-value muted small">{market.sold_comps_count}</span>
      </div>

      {market.market_source && (
        <div className="deal-row sealed-catalog-market-source">
          <span className="deal-row-label">Source</span>
          <span className="deal-row-value muted small">
            {market.market_source}
            {market.market_source_updated_at
              ? ` · ${formatStaleness(market.market_source_updated_at)}`
              : ""}
          </span>
        </div>
      )}

      <p className="deal-caveat muted small">
        {market.unavailable
          ? "No listings API key configured — the market median needs eBay sold comps."
          : market.empty
            ? "A key is set but eBay returned 0 confirmed sales for this product."
            : "Median of recent eBay sold comps — actual transactions, not a listed estimate."}
      </p>
    </div>
  );
}