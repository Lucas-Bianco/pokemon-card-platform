// Shared marketing-site content. Copy preserved verbatim from docs/index.html.
// Roadmap + pipeline + stack data live here so section components stay presentational.

export type Phase = {
  n: string;
  title: string;
  subtitle: string;
  status: "done" | "progress" | "planned";
  /** Optional count-up stat shown on done phases (e.g. coverage delta). */
  stat?: { label: string; from: string; to: string };
};

export const ROADMAP: Phase[] = [
  { n: "00", title: "Foundation", subtitle: "Card catalog, pricing layer, collection store", status: "done" },
  { n: "01a", title: "Recognition engine", subtitle: "Photo → identified, valued card · 20,391 cards indexed", status: "done" },
  { n: "01b", title: "Scan PWA", subtitle: "Camera capture, top-3 picker · 100% precision on real photos", status: "done" },
  {
    n: "01c",
    title: "Robust card detection",
    subtitle: "Strategy chain scored by recognition · coverage 31% → 61%, 0 regressions",
    status: "done",
    stat: { label: "Coverage", from: "31%", to: "61%" },
  },
  { n: "02", title: "Portfolio tracker", subtitle: "Cost basis, P/L, price history charts · honest empty states", status: "done" },
  {
    n: "03a",
    title: "Card centering",
    subtitle: "Geometric PSA cap from border measurement · correct, coverage blocked on real photos",
    status: "done",
  },
  {
    n: "03b",
    title: "Grading data infrastructure",
    subtitle:
      "Rectified-crop persistence, grade-label schema + self-annotation, graded-price provider, grading-upside spread",
    status: "done",
  },
  {
    n: "03d",
    title: "Grading Studio",
    subtitle: "Honest user-assisted grade-band calculator · the transparent form of the grade predictor (a learned one is impossible with 0 labelled scans)",
    status: "done",
  },
  {
    n: "03",
    title: "Grade predictor",
    subtitle:
      "Corner / edge / surface scoring + P(grade) — Grading Studio honest calculator shipped; full learned predictor still planned, needs labelled data the project has 0 of",
    status: "progress",
  },
  { n: "04", title: "Bulk cataloger", subtitle: "Detect and log every card in one photo · shipped", status: "done" },
  { n: "05", title: "Deal sniper & sealed EV", subtitle: "Rip-vs-flip deal sniper + deal alerts + sold-comps shipped; sealed flip-edge shipped; sealed purchase ledger + profit tracker + Google Sheets sync shipped; rip EV (expected pull value) still planned — needs pull-rate data", status: "progress" },
  { n: "06", title: "Set-completion optimizer", subtitle: "Per-set owned/missing checklist + honest cost-to-complete · shipped", status: "done" },
  { n: "07", title: "Authenticity check (honest counterfeit tool)", subtitle: "Catalog-consistency auto-check (printed # vs catalog #) + rarity-gated physical checklist · never a fake/real verdict · CV-forensic detector disproven on this data (0 confirmed fakes) · shipped", status: "done" },
  { n: "09", title: "Sealed-product catalog + MSRP", subtitle: "Curated master catalog of sealed products (ETB / booster box / pack / premium) with MSRP — the keystone that unblocks scan-to-log, MSRP-vs-market, and rip EV · shipped (catalog tab + browse/search filters; curated seed, not magic auto-update)", status: "done" },
  { n: "10", title: "Scan-to-log sealed products", subtitle: "Log a sealed buy straight from a catalog row (by slug) → pre-fill the purchase ledger · shipped (catalog-driven form); camera-OCR scan-to-box match is a follow-up", status: "done" },
  { n: "11", title: "MSRP vs market view", subtitle: "Show MSRP vs the live sold-comps median for any sealed product, with the same honest unavailable/empty flags as the sold-comps view · shipped", status: "done" },
  { n: "12", title: "Price lookup by name", subtitle: "Type a card name → see matches with their latest market price, no scan needed · reuses the card catalog + price layer · shipped (new Prices tab)", status: "done" },
  { n: "13", title: "Online shopping assistant", subtitle: "Paste an eBay listing URL → instant deal / worth / authenticity read · single-listing fetch (getSingleItem) + sealed/card match + sold-comps-median deal verdict + Phase 07 authenticity guide · composes the deal-sniper + flip-edge + price + sold-comps + authenticity pillars · read-only, honest empty states, never a fake/real verdict · shipped (new Shop tab)", status: "done" },
  { n: "14", title: "Publishable-app overhaul", subtitle: "Make it a real app you can publish — packaged desktop app, hosted service, or polished open-source release (decision pending)", status: "planned" },
  { n: "15", title: "Private repo + Pages relocation", subtitle: "Make the repo private (one command) and relocate the marketing site so Pages survives — needs a paid GitHub plan or a separate public/Cloudflare Pages host", status: "planned" },
  { n: "16", title: "Proof of sales", subtitle: "Every market price backed by viewable eBay sold-comps (date, price, condition, source link) — actual transactions, not a listed estimate; the honest differentiator (99% of price apps assert a number and never prove anyone paid it). Reusable ProofOfSales block under ScanResult's price + per-row toggle on SealedDeals/SealedLedger; honest unavailable/empty states, never $0", status: "done" },
  { n: "17", title: "Multi-TCG platform (Magic + Topps)", subtitle: "Extend beyond Pokémon to Magic: The Gathering (Scryfall API) and Topps sports cards — separate catalogs, price providers, and recognition models per domain", status: "planned" },
  { n: "18", title: "Collection insurance value", subtitle: "Sum latest_price across the vault in a conservative/median/aggressive band + a printable schedule — the thing a serious collector actually needs; honest 'no price → excluded' never $0; reuses the price layer. Shipped as GET /collection/insurance + InsuranceValue panel in PortfolioView (3-band tiles, printable per-card schedule, source + staleness on every line)", status: "done" },
  { n: "19", title: "Trade-up / sell-now simulator", subtitle: "For a card you own, two honest exit legs side by side: sell-raw-now (proven eBay sold-comps median − selling fee) vs grade-then-sell (graded market − grading fee − selling fee, assuming the target grade). A measured PSA centering cap below the target flags that grade as unreachable. A listed ask is shown for context only — never used as the sell price. The read is descriptive ('Grade, then sell' / 'Sell raw now'), never a forecast. Shipped as GET /cards/{id}/trade-up + TradeUp panel in ScanResult (pre-filled from the scan's centering cap) and CardDetail; every null leg is an em dash + 'no estimate', never $0", status: "done" },
  { n: "20", title: "Price-alert thresholds (pull, not push)", subtitle: "An on-demand pull, not a push promise: a 'Check now' button runs one AlertEngine tick against the listings known right now and surfaces freshly-fired events (prepended, deduped by id). Reuses the exact engine the background poll loop uses, so a pull and a poll can never disagree. The in-app AlertEvent row is the always-available floor; push/email only if you've turned those on — the copy never says 'we'll notify you'. Shipped as POST /alerts/check + Check now in AlertsFeed (empty + populated states) with honest 'N new' / 'nothing new yet' / verbatim-error notes. Also fixed a latent production bug: ListingsService.refresh_listings commits, and calling it inside the engine's per-watch savepoint silently suppressed every listing-based alert in the poll loop — refresh now runs outside the savepoint", status: "done" },
  { n: "21", title: "Shareable binder", subtitle: "A curated, ordered subset of your vault you show off — each slot backed by its single most-recent *proven* eBay sale (an actual transaction, not a listed ask); a slot with no proven sale is shown honestly, never a fabricated $0. 'Shareable' is a standalone self-contained HTML download (inline CSS, hotlinked images) — you host/attach it anywhere, no server uptime required (local-first, not a public-page promise). Shipped as binder_items table + BinderService (add/remove/reorder/note/export) + 6 routes + a 14th Binder tab (grid, move up/down, inline note, Export/Print) + Add-to-binder from CardDetail", status: "done" },
  { n: "22", title: "Market trend charts", subtitle: "Per-card price history charts from the append-only snapshot log. The PriceChart (already in CardDetail + PortfolioView History) now states the point count + an honest 'depth depends on price-refresh cadence (snapshots are append-only, never trimmed)' caveat — a short line is a young history, not censored data. (The earlier 'blocked on retention' note was a false premise: snapshots were never trimmed.)", status: "done" },
  { n: "08", title: "On-device inference", subtitle: "Quantized model in-browser — scanning with no server", status: "planned" },
];

export const SHIPPED_COUNT = ROADMAP.filter((p) => p.status === "done").length;
export const TOTAL_COUNT = ROADMAP.length;

export type PipeStep = {
  title: string;
  detail: string;
};

export const PIPELINE: PipeStep[] = [
  {
    title: "Detect & rectify",
    detail:
      "Find the card's corners in-frame and perspective-warp it flat. Runs on-device in WebAssembly to drive a live camera overlay.",
  },
  {
    title: "Visual embedding match",
    detail:
      "Embed the crop and search every card in the catalog by visual similarity. Returns ranked candidates, never one blind guess.",
  },
  {
    title: "Targeted OCR",
    detail:
      "Read the collector number — a unique key for any card — from a known position on the rectified image.",
  },
  {
    title: "Fusion & calibrated confidence",
    detail:
      "Combine both signals. Agreement auto-confirms; disagreement surfaces the top three and logs the user's pick as training data.",
  },
  {
    title: "Variant disambiguation",
    detail:
      "Specular analysis separates holo from reverse-holo foiling — the difference that most scanners silently get wrong.",
  },
];

export const PIPELINE_NOTE =
  "Rectification is the load-bearing step: it makes both engines more accurate, shrinks the network payload, and produces exactly the normalized image the grading module needs later.";

export const STACK_FRONTEND = ["React", "TypeScript", "OpenCV.js / WASM", "PWA"];
export const STACK_BACKEND = ["FastAPI", "CLIP / DINOv2", "FAISS", "PaddleOCR", "Postgres"];

export const STACK_FRONTEND_BLURB = "Installable PWA — one codebase for phone camera and desktop.";
export const STACK_BACKEND_BLURB = "Python, deliberately — the CV and ML ecosystem the later phases depend on.";

// The bold lead-in "Runs entirely on your own machine." is rendered separately
// in Stack.tsx, so this note begins with the supporting sentence to avoid a
// duplicated lead phrase in the rendered output.
export const STACK_LOCAL_NOTE =
  "Compute is local — recognition, embedding, search, and OCR never leave the device. Only the card catalog and price data sync over the network, so scanning still works offline, in a card shop, on bad signal.";