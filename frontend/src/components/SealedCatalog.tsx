import { useEffect, useRef, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import { getSealedProducts } from "../api/client";
import type {
  SealedPrintStatus,
  SealedProduct,
  SealedProductType,
  SealedProductsResponse,
} from "../api/types";
import { formatMoney } from "../lib/format";
import { staggerContainer, staggerItem } from "./motion";

// The Catalog tab (Phase A, roadmap row 09): a browsable, searchable reference
// catalog of every sealed Pokémon product that contains card packs — booster
// packs, booster boxes, ETBs, collection boxes, tins, premium bundles — Base era
// → newest, with an honest MSRP and an in-print / out-of-print / unknown tag.
//
// HONESTY (the whole feature):
// - The seed is curated + in-repo, NOT "magic auto-update" — there is no official
//   sealed-product API. A future semi-automated community sync (Pokellector /
//   TCGplayer) with manual review is a documented follow-up. The toolbar says so.
// - `msrp` is null for products with no official US MSRP (booster boxes, premiums)
//   → the card shows "no MSRP" via formatMoney's em dash, NEVER a fabricated $0.
// - `print_status` is a best-effort tag, never a guarantee (products re-enter print).
//
// Visual language: reuses the `.deal-*` card idiom (surface + chip pill) for
// consistency with the Deals/Sealed tabs; only additive `.sealed-catalog-*` classes
// are introduced (toolbar, chip variants, caveat). Fetches on mount + on any
// filter change (debounced 300ms for the text query; immediate for the selects).

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
        follow-up, not magic auto-update.
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
      </p>
    </>
  );
}

function SealedCatalogCard({ product }: { product: SealedProduct }) {
  const reduced = useReducedMotion();
  const year = releasedYear(product.released_at);

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
    </motion.li>
  );
}