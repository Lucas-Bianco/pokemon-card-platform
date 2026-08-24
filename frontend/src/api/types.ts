export type RecognitionStatus = "confident" | "ambiguous" | "not_found";

export interface Price {
  source: string;
  variant: string;
  low: number | null;
  mid: number | null;
  high: number | null;
  market: number | null;
  source_updated_at: string | null;
}

export interface CardSummary {
  id: string;
  name: string;
  number: string;
  rarity: string | null;
  set_id: string;
  set_name: string;
  image_small: string | null;
  image_large: string | null;
}

export interface Candidate {
  card_id: string;
  name: string;
  set_name: string;
  number: string;
  image_small: string | null;
  visual_score: number;
}

// A geometric measurement of the *front* border only, and only ever a ceiling: it
// says what centering rules out, never what the card grades. `psa_cap_certain` is
// false when the ± interval straddles a band boundary — at a 20px border one pixel
// is ±2.5 share points and the PSA 10→9 band is only 5 points wide, so the reading
// genuinely cannot say which side the card falls on.
export interface Centering {
  left_right: [number, number];
  top_bottom: [number, number];
  worst_axis: number;
  uncertainty: number;
  psa_cap: number | null;
  psa_cap_certain: boolean;
}

export interface RecognizeResponse {
  status: RecognitionStatus;
  confidence: number;
  visual_margin: number;
  card: CardSummary | null;
  price: Price | null;
  candidates: Candidate[];
  collector_number_read: string | null;
  centering: Centering | null;
  // Phase 3b: the persisted rectified crop's relative path ("rectified/<uuid>.png"),
  // or null when no crop was produced. Surfaced so the frontend can pass it back
  // to POST /scans and record it on the scan_logs row. Optional on the TS side
  // only to keep existing mock literals compiling; the backend always sends it.
  rectified_path?: string | null;
}

// Phase 4 bulk cataloger: one binder-page photo → N independent scan verdicts.
// Each result carries its own status/price/rectified_path; per-card statuses are
// NEVER collapsed into one batch status. `batch_id` groups the cards so the
// client can thread it back through POST /scans per card. Mirrors
// BatchRecognizeOut in backend api.py field-for-field.
export interface BatchRecognizeResponse {
  batch_id: string;
  count: number;
  results: RecognizeResponse[];
}

export interface CollectionItem {
  id: number;
  card_id: string;
  card_name: string;
  variant: string;
  quantity: number;
  acquired_price: number | null;
}

export interface Valuation {
  market_value: number;
  cost_basis: number;
  unrealized: number;
  unpriced_items: number;
}

// One observed price in a history series. source and source_updated_at travel with
// every point so a chart never presents a number without saying where it came from —
// the same staleness rule the single-price endpoint follows.
export interface PricePoint {
  fetched_at: string;
  source: string;
  variant: string;
  market: number | null;
  source_updated_at: string;
}

export interface PriceHistory {
  card_id: string;
  variant: string;
  points: PricePoint[];
}

// A holding enriched with its resolved market price and unrealized P/L. market_price /
// unrealized are null when the item is unpriced; unrealized is also null when there is
// no cost basis, because a price with no purchase cost is not a gain — the UI shows an
// em dash, never market value dressed up as profit.
export interface PortfolioItem {
  id: number;
  card_id: string;
  card_name: string;
  set_id: string;
  set_name: string;
  variant: string;
  quantity: number;
  acquired_price: number | null;
  acquired_at: string | null;
  condition: string | null;
  notes: string | null;
  market_price: number | null;
  market_source: string | null;
  market_source_updated_at: string | null;
  unrealized: number | null;
  priced: boolean;
}

export interface Allocation {
  set_id: string;
  set_name: string;
  market_value: number;
  cost_basis: number;
  item_count: number;
}

export interface PortfolioSummary {
  market_value: number;
  cost_basis: number;
  unrealized: number;
  unpriced_items: number;
  priced_items: number;
  allocation: Allocation[];
  top_gainers: PortfolioItem[];
  top_losers: PortfolioItem[];
}

export interface Portfolio {
  summary: PortfolioSummary;
  items: PortfolioItem[];
}

// One holding in a printable insurance schedule — low/market/high provenance from
// the same snapshot the rest of the app uses. Priced is false when there is no
// usable market figure; such a line still appears (so nothing is silently dropped)
// but contributes to no band total.
export interface InsuranceLine {
  card_id: string;
  card_name: string;
  set_name: string;
  variant: string;
  quantity: number;
  low: number | null;
  market: number | null;
  high: number | null;
  source: string | null;
  source_updated_at: string | null;
  priced: boolean;
}

// Replacement-value bands for the collection. conservative = low (fallback to
// market); median = market; aggressive = high (fallback to market). Unpriced cards
// are excluded from the totals and counted in unpriced_items — never $0.
export interface InsuranceValue {
  conservative: number;
  median: number;
  aggressive: number;
  priced_items: number;
  unpriced_items: number;
  schedule: InsuranceLine[];
  caveat: string;
}

export interface Scan {
  id: number;
  status: string;
  predicted_card_id: string | null;
  corrected_card_id: string | null;
  confirmed: boolean;
  confidence: number | null;
  visual_margin: number | null;
  collector_number_read: string | null;
}

// The third-party graders a self-annotation can name. The backend stores grader
// as a free string, but the UI only offers these three — the labels Lucas mails
// in himself are the project's only honest labelled dataset, so the choice is
// constrained to the services that actually grade Pokémon cards.
export type Grader = "PSA" | "CGC" | "BGS";

// One tier of the raw-vs-graded price spread (raw / psa9 / psa10). `market` may
// be null when a graded comp exists in the source without a market figure, and
// the whole tier is null when the underlying snapshot is missing — never a
// fabricated $0 (the project's sacred convention; see PortfolioView.tsx, which
// renders an em dash and "no market price" rather than a flat zero). `source`
// and `source_updated_at` travel with every figure so the UI can say where a
// number came from and how old it is.
export interface GradingTier {
  market: number | null;
  source: string;
  source_updated_at: string | null;
}

// The raw-vs-graded price SPREAD, not a grade prediction. `upside_to_10` is null
// unless BOTH raw_price and psa10 are present; a fabricated number from a
// missing input would be confidently-wrong. `graded_prices_unavailable` is true
// only when psa9 AND psa10 are both null, signalling the UI to show "graded
// prices unavailable — set a graded-price provider key" instead of a misleading
// panel of zeroes. Mirrors GradingUpsideOut in backend api.py field-for-field.
export interface GradingUpside {
  card_id: string;
  variant: string;
  raw_price: GradingTier | null;
  psa9: GradingTier | null;
  psa10: GradingTier | null;
  grading_fee: number;
  upside_to_10: number | null;
  graded_prices_unavailable: boolean;
}

// A third-party grade attached to one scan — the only honest labelled data the
// project collects. `variant` is nullable: a scan that never picked a variant
// carries an honest None, never a fabricated "normal". One label per scan;
// re-grading upserts the same row, so `id` is stable across corrections. Mirrors
// GradingLabelOut in backend api.py field-for-field.
export interface GradingLabel {
  id: number;
  scan_id: number;
  card_id: string;
  variant: string | null;
  grade: number;
  grader: Grader;
  cert_number: string | null;
  notes: string | null;
  created_at: string;
}

// One row from the catalog search endpoint (GET /cards?name=...). The backend
// returns the full CardOut shape; we type the subset the Browse list renders,
// so a card with no thumbnail still has a name to tap. Mirrors CardOut.
export interface CardSearchResult {
  id: string;
  name: string;
  number: string;
  set_id: string;
  set_name: string;
  image_small: string | null;
  image_large: string | null;
}

// One marketplace listing from the newest snapshot. `source` is always present
// (the backend never fabricates a default); every nullable column surfaces as
// null when the source omits it. Mirrors ListingOut in backend
// alerts/api_models.py field-for-field.
export interface Listing {
  listing_id: string;
  title: string | null;
  price: number | null;
  currency: string | null;
  listing_type: string | null;
  auction_end_at: string | null;
  url: string | null;
  condition: string | null;
  source: string;
  fetched_at: string;
}

// The POST /cards/{id}/listings?variant= response. `listings_unavailable` is
// true when no listings provider key is configured (the backend never fakes
// listings); false means the source was queried, just possibly empty.
export interface ListingsResponse {
  listings: Listing[];
  listings_unavailable: boolean;
}

// The alert kinds a watch can listen for. Mirrors the backend's _ALERT_TYPES
// set (api.py); the watchlist endpoint validates membership and 422s on
// anything else. Keep this in lockstep with that set.
export type AlertType =
  | "restock"
  | "new_listing"
  | "price_target"
  | "auction_ending"
  | "drop_time"
  | "deal";

// One watch subscription. `active` is the on/off toggle the More tab flips;
// `last_fired_at` is engine state surfaced for display. Mirrors WatchOut in
// backend alerts/api_models.py field-for-field; every nullable column
// surfaces as null, never a fabricated default.
export interface Watch {
  id: number;
  card_id: string | null;
  subject_label: string | null;
  variant: string | null;
  alert_type: AlertType;
  target_price: number | null;
  drop_at: string | null;
  lead_time_min: number | null;
  auction_window_min: number | null;
  active: boolean;
  last_fired_at: string | null;
  created_at: string;
}

// Inbound watch. `card_id` is optional so a watch can target a non-card subject
// (e.g. a Pokémon Center vending drop) via `subject_label`. Per-type required
// fields (target_price for price_target, drop_at for drop_time) are validated
// by the endpoint, not by the type — Pydantic cannot express the conditional,
// and neither can TS cleanly. Mirrors WatchCreate.
export interface WatchCreate {
  card_id?: string | null;
  subject_label?: string | null;
  variant?: string | null;
  alert_type: AlertType;
  target_price?: number | null;
  drop_at?: string | null;
  lead_time_min?: number | null;
  auction_window_min?: number | null;
}

// Partial update to a watch. Every field is optional; a field that is absent
// (undefined) is left untouched by the backend. Use null to clear a field
// explicitly where the backend allows it. Mirrors WatchPatch.
export interface WatchPatch {
  active?: boolean | null;
  target_price?: number | null;
  drop_at?: string | null;
  lead_time_min?: number | null;
  auction_window_min?: number | null;
}

// One fired alert for the in-app notification feed. `read_at` is null until the
// user opens it; the feed's unread badge is computed from it. `context` is a
// free-form string — the engine may JSON-encode extra detail (e.g. a listing
// url) there, so the feed tries to parse it for a deep link. Mirrors
// AlertEventOut field-for-field.
export interface AlertEvent {
  id: number;
  watch_id: number | null;
  card_id: string | null;
  alert_type: AlertType;
  message: string;
  context: string | null;
  delivered_push: boolean;
  delivered_email: boolean;
  read_at: string | null;
  created_at: string;
}

// A Web Push subscription endpoint + its ECDH key material. The browser
// generates p256dh/auth on subscribe; they rotate, so the upsert updates them
// when the same endpoint re-subscribes. Mirrors PushSubscribeIn.
export interface PushSubscription {
  endpoint: string;
  p256dh: string;
  auth: string;
}

// Phase 05 deal sniper. One market price the engine compared the listing
// against (raw / psa9 / psa10). `source` and `source_updated_at` travel with
// every figure so a deal card never presents a number without saying where
// it came from and how old it is — the same staleness rule PricePoint follows.
// Mirrors PricePointOut in backend deals/api_models.py.
export interface DealPricePoint {
  price: number;
  source: string;
  source_updated_at: string;
}

// The deal thresholds the engine applied; echoed in the response so the UI can
// label why a listing was flagged (or not). Mirrors ThresholdsOut.
export interface DealThresholds {
  deal_rip_min_abs: number;
  deal_rip_min_pct: number;
  deal_flip_min_abs: number;
}

// One ranked listing with its rip/flip edges and flags. `rip_edge` /
// `flip_edge_to_9` / `flip_edge_to_10` are null when the corresponding market
// input is missing — never a fabricated $0. `raw_market` / `psa9_comp` /
// `psa10_comp` are null when no snapshot exists. `is_rip` / `is_flip` are
// honest booleans against the thresholds; a missing edge is never a deal.
// Mirrors DealAssessmentOut field-for-field.
export interface DealAssessment {
  listing_id: string;
  title: string | null;
  listing_price: number | null;
  currency: string | null;
  url: string | null;
  condition: string | null;
  listing_type: string | null;
  auction_end_at: string | null;
  fetched_at: string;
  raw_market: DealPricePoint | null;
  rip_edge: number | null;
  psa9_comp: DealPricePoint | null;
  psa10_comp: DealPricePoint | null;
  flip_edge_to_9: number | null;
  flip_edge_to_10: number | null;
  grading_fee: number;
  deal_score: number | null;
  is_rip: boolean;
  is_flip: boolean;
}

// Per-card or cross-card deal feed response. `listings_unavailable` is true
// when no listings_api_key is configured (honest — no provider configured,
// never fake listings). `listings_empty` is true when a key IS set but no
// listings exist (the source was queried, just empty). For the cross-card
// feed, `card_id` and `variant` are null and the flags merge across all
// assessed cards. Mirrors DealsResponse field-for-field.
export interface DealsResponse {
  card_id: string | null;
  variant: string | null;
  listings_unavailable: boolean;
  listings_empty: boolean;
  deals: DealAssessment[];
  thresholds: DealThresholds;
}

// One recent eBay sold comp backing a card's market price. Sold comps are
// EVIDENCE, not a price target — the UI never presents them as the card's
// price, only as "these just sold at $X". `price` is always present (a comp
// with no price isn't evidence); every other column surfaces as null when the
// source omits it. `source` is always present (the backend never fabricates a
// default). Mirrors SoldCompOut in backend api_models.py.
export interface SoldComp {
  listing_id: string;
  title: string | null;
  price: number;
  currency: string | null;
  url: string | null;
  condition: string | null;
  sold_at: string | null;
  source: string;
}

// The GET /cards/{id}/sold-comps?variant= response. `sold_comps_unavailable`
// is true when no listings provider key is configured (honest — no provider
// configured, never fake comps); `sold_comps_empty` is true when a key IS set
// but the source returned no recent sales (the source was queried, just
// empty). Mirrors SoldCompsResponse field-for-field.
export interface SoldCompsResponse {
  card_id: string;
  variant: string;
  sold_comps: SoldComp[];
  sold_comps_unavailable: boolean;
  sold_comps_empty: boolean;
}

// Phase 05c — sealed-product flip-edge (query-keyed, eBay). Mirrors backend
// SealedPricePointOut / SealedThresholdsOut / SealedDealAssessmentOut /
// SealedDealsResponse field-for-field. Sealed products (booster boxes, ETBs,
// collection boxes, packs) are query-keyed — they carry the free-text `query`
// the user searched for, never a card_id/variant. Every nullable field
// surfaces as null when the source omits it; `flip_edge` / `deal_score` /
// `sealed_market` are null when there are no sold comps — never a fabricated
// $0 (the project's sacred convention; the UI renders an em dash).

// The market reference a sealed listing was compared against (median of recent
// sold comps). `source` + `source_updated_at` travel with the figure so a deal
// card never presents a number without saying where it came from — sold comps
// expose no per-sale source stamp, so `source_updated_at` is null.
export interface SealedPricePoint {
  price: number;
  source: string;
  source_updated_at: string | null;
}

// The deal thresholds the engine applied; echoed in the response so the UI can
// label why a listing was flagged (or not). Mirrors SealedThresholdsOut.
export interface SealedThresholds {
  sealed_flip_min_abs: number;
  sealed_flip_min_pct: number;
}

// One ranked sealed listing with its flip-edge + flag. `flip_edge` /
// `deal_score` are null when `sealed_market` is null (no sold comps) or the
// listing price is missing — never a fabricated $0. `sealed_market` is null
// when no sold comps exist. `is_flip` is an honest boolean against the
// thresholds; a null edge is never a deal. Mirrors SealedDealAssessmentOut
// field-for-field.
export interface SealedDealAssessment {
  query: string;
  listing_id: string;
  title: string | null;
  listing_price: number | null;
  currency: string | null;
  url: string | null;
  condition: string | null;
  listing_type: string | null;
  auction_end_at: string | null;
  fetched_at: string;
  sealed_market: SealedPricePoint | null;
  flip_edge: number | null;
  deal_score: number | null;
  is_flip: boolean;
}

// The GET /sealed/deals?q=&limit= response. `listings_unavailable` is true when
// no listings_api_key is configured (sealed reuses the eBay listings key — no
// separate sealed key); `listings_empty` is true when a key IS set but no
// active listings were found. `comps_unavailable` / `comps_empty` mirror that
// for the sold comps that establish `sealed_market`. `sealed_market` is null
// when no sold comps -> every `flip_edge` is null (honest, never $0). Mirrors
// SealedDealsResponse field-for-field.
export interface SealedDealsResponse {
  query: string;
  limit: number;
  listings_unavailable: boolean;
  listings_empty: boolean;
  comps_unavailable: boolean;
  comps_empty: boolean;
  sealed_market: SealedPricePoint | null;
  deals: SealedDealAssessment[];
  thresholds: SealedThresholds;
}

// Phase 16 — proof of sales (sealed). The individual recently-sold eBay listings
// behind the median `sealed_market` shown on /sealed/deals — actual transactions
// (date/price/condition/title/link), so the user sees real people paid real money,
// not a retailer's listed estimate. Query-keyed (like sealed deals), on-demand only
// (never persisted). Mirrors `SealedSoldCompOut` / `SealedSoldCompsResponse`
// field-for-field. Honest empty flags mirror the card sold-comps pattern:
// `sold_comps_unavailable` (no listings_api key) vs `sold_comps_empty` (key set, 0 sales).

export interface SealedSoldComp {
  query: string;
  listing_id: string;
  price: number;
  title: string | null;
  currency: string | null;
  url: string | null;
  condition: string | null;
  sold_at: string | null;
  source: string;
}

export interface SealedSoldCompsResponse {
  query: string;
  limit: number;
  sold_comps: SealedSoldComp[];
  sold_comps_unavailable: boolean;
  sold_comps_empty: boolean;
}

// Phase A (roadmap row 09) — sealed-product reference catalog. A browsable,
// searchable list of every sealed Pokémon product that contains card packs
// (booster packs, booster boxes, ETBs, collection boxes, tins, premium bundles)
// Base era → newest, with an honest MSRP (`msrp` is null when no official US MSRP
// exists — booster boxes, premiums — and the UI shows "no MSRP", never $0) and an
// in_print / out_of_print / unknown tag. Curated in-repo seed (NOT magic auto-
// update — no official sealed-product API exists; a future semi-automated
// community sync with manual review is a documented follow-up). Mirrors backend
// SealedProductOut / SealedProductsResponse field-for-field.

export type SealedProductType =
  | "booster_pack"
  | "booster_box"
  | "etb"
  | "collection_box"
  | "tin"
  | "premium_bundle"
  | "other";

export type SealedPrintStatus = "in_print" | "out_of_print" | "unknown";

export interface SealedProduct {
  slug: string;
  name: string;
  era: string | null;
  product_type: SealedProductType;
  msrp: number | null;
  msrp_currency: string;
  print_status: SealedPrintStatus;
  source_url: string | null;
  image_url: string | null;
  released_at: string | null;
  source: string;
  created_at: string;
}

export interface SealedProductsResponse {
  products: SealedProduct[];
  count: number;
  product_type: SealedProductType | null;
  print_status: SealedPrintStatus | null;
}

// Phase B — scan-to-log. Log a sealed buy straight from a catalog row by slug.
// The product's name + product_type are resolved server-side, so the client only
// sends the slug + the purchase facts. `quantity` defaults to 1; `cost_per_unit`
// is required (a logged buy always has a cost). Optional fields are null. Mirrors
// backend SealedScanLogIn field-for-field.
export interface SealedScanLogRequest {
  slug: string;
  quantity?: number;
  cost_per_unit: number;
  source?: string | null;
  listing_url?: string | null;
  notes?: string | null;
  bought_at?: string | null;
}

// Phase C — MSRP vs market. One catalog product's curated MSRP compared to its
// live eBay sold-comps median. Every nullable figure is null (never 0): `msrp`
// is null where no official US MSRP exists; `market_median` is null when there
// are no comps; `delta` is null unless BOTH msrp and market_median are real. The
// honest flags mirror /sealed/sold-comps: `unavailable` = no listings key (the
// provider returns [] without the network); `empty` = key set but 0 comps.
// Mirrors backend SealedProductMarketOut field-for-field.
export interface SealedProductMarket {
  slug: string;
  name: string;
  msrp: number | null;
  msrp_currency: string;
  market_median: number | null;
  market_source: string | null;
  market_source_updated_at: string | null;
  sold_comps_count: number;
  delta: number | null;
  unavailable: boolean;
  empty: boolean;
}

// Phase D — card price lookup. One card match for the Prices tab's name -> price
// flow. `market` is the latest snapshot's market figure, or null when no snapshot
// exists (honest "no market price", never a fabricated 0). `source` +
// `source_updated_at` travel with the figure so the UI can say where it came from
// and how stale it is; both are null for an unpriced card. Mirrors backend
// CardLookupItemOut field-for-field.
export interface CardLookupItem {
  card_id: string;
  name: string;
  set_id: string;
  set_name: string;
  number: string;
  rarity: string | null;
  image_small: string | null;
  image_large: string | null;
  market: number | null;
  source: string | null;
  source_updated_at: string | null;
}

// Phase 05d — sealed-purchase ledger. The user logs sealed boxes/packs they
// bought (query-keyed, like sealed deals); the backend periodically values them
// against the eBay sold-comps median and tracks profit. Every nullable market
// field surfaces as null when unvalued — never a fabricated $0 (the project's
// sacred convention; the UI renders an em dash via formatMoney). Mirrors
// backend SealedPurchaseOut / SealedLedgerResponse / ValuationRefreshResult
// field-for-field.

// One logged purchase, enriched with its latest valuation. `value_per_unit` /
// `total_current_value` / `profit` / `profit_pct` are null until the purchase is
// valued against sold comps — never $0. `market_fetched_at` / `market_source`
// travel with the valuation so a card never presents a number without saying
// where it came from. `valued` is the honest boolean the UI branches on.
export interface SealedLedgerEntry {
  id: number;
  query: string;
  product_type: string | null;
  quantity: number;
  cost_per_unit: number;
  total_cost: number;
  source: string | null;
  listing_url: string | null;
  notes: string | null;
  bought_at: string;
  created_at: string;
  value_per_unit: number | null;
  total_current_value: number | null;
  profit: number | null;
  profit_pct: number | null;
  market_fetched_at: string | null;
  market_source: string | null;
  valued: boolean;
}

// The GET /sealed/ledger response. `listings_unavailable` is true when no
// listings provider key is configured (honest — no provider, never fake comps);
// false means valuations can run, just possibly all unvalued.
export interface SealedLedgerResponse {
  purchases: SealedLedgerEntry[];
  listings_unavailable: boolean;
}

// The POST /sealed/ledger/valuate response. `valued` is the count refreshed;
// `skipped_no_comps` is the count with no sold comps to value against;
// `skipped_no_key` is true when the eBay key is missing (the UI shows the
// "set CARDPLATFORM_LISTINGS_API_KEY" notice instead of a count).
export interface ValuationRefreshResult {
  valued: number;
  skipped_no_comps: number;
  skipped_no_key: boolean;
}

// The POST /sealed/ledger response (one logged purchase, echoed back). Mirrors
// SealedPurchaseOut in backend api.py — the valuation fields are NOT here (a
// freshly logged purchase is unvalued); the client reloads the ledger to fetch
// the enriched SealedLedgerEntry shape.
export interface SealedPurchaseOut {
  id: number;
  query: string;
  product_type: string | null;
  quantity: number;
  cost_per_unit: number;
  source: string | null;
  listing_url: string | null;
  notes: string | null;
  bought_at: string;
  created_at: string;
}

// The POST /sealed/ledger/sync response. `synced` is false when Google Sheets
// isn't configured (no OAuth secret at data/credentials.json or no
// CARDPLATFORM_GOOGLE_SHEET_ID) — the backend returns `reason: "not_configured"`
// without making any network call or raising, so the UI can show honest setup
// instructions rather than fabricating success. `rows` is the count written on
// a successful sync. Mirrors SheetsSyncResult in backend api.py field-for-field.
export interface SheetsSyncResult {
  synced: boolean;
  rows: number;
  reason: string | null;
}

// Phase 06 — set completion. Per-set owned/missing checklist + an honest
// estimated cost to complete. `market`/`est_cost_to_complete` are null when a
// missing card has no price snapshot — never a fabricated $0. `source` +
// `source_updated_at` travel with each priced missing card (the "" sentinel
// becomes null on the wire). `est_cost_to_complete` is 0 only when the set is
// complete (missing === 0); null when every missing card is unpriced; otherwise
// the sum of the priced missing cards (a partial estimate — `unpriced_missing`
// is always surfaced so the sum is never mistaken for complete).
export interface SetProgress {
  id: string;
  name: string;
  series: string | null;
  release_date: string | null;
  total: number | null;
  printed_total: number | null;
  owned: number;
  checklist_size: number;
  pct_complete: number;
}

export interface ChecklistEntry {
  card_id: string;
  name: string;
  number: string;
  rarity: string | null;
  image_small: string | null;
  owned: boolean;
  market: number | null;
  source: string | null;
  source_updated_at: string | null;
}

export interface CompletionSummary {
  owned: number;
  checklist_size: number;
  missing: number;
  pct_complete: number;
  est_cost_to_complete: number | null;
  unpriced_missing: number;
}

export interface SetCompletion {
  id: string;
  name: string;
  series: string | null;
  release_date: string | null;
  total: number | null;
  printed_total: number | null;
  cards: ChecklistEntry[];
  summary: CompletionSummary;
}

// Phase 07 — honest counterfeit tool. The ONE auto-signal the dataset supports
// (printed collector number vs the recognized card's catalog number) plus a
// user-driven physical checklist. Image-forensic detection (halftone/holo/
// sharpness/color-delta) was tested and disproven on the 600x825 rectified phone
// crops, and the project has zero confirmed-counterfeit samples to calibrate a
// learned check against — so this is a guide, never a fake/real verdict. A
// consistency `mismatch` is explicitly "wrong recognition OR counterfeit,
// indistinguishable". Mirrors AuthenticityOut / ConsistencyOut / ChecklistItemOut
// in backend api.py field-for-field.
export type ConsistencyMatch = "match" | "mismatch" | "unread" | "no_card";

export interface Consistency {
  printed_number: string | null;
  catalog_number: string | null;
  card_id: string | null;
  card_name: string | null;
  match: ConsistencyMatch;
  note: string;
}

export interface ChecklistItem {
  id: string;
  title: string;
  what_to_check: string;
  caveat: string;
  // False when the check is irrelevant to the card type (e.g. the holo light
  // test for a non-holo card). The UI renders those as N/A, not hidden.
  applies: boolean;
}

export interface Authenticity {
  caveat: string;
  consistency: Consistency;
  checklist: ChecklistItem[];
}

// Phase E — online shopping assistant. Paste-an-URL assessment of one eBay
// listing: the engine fetches the listing, matches it to the catalog (card or
// sealed product), compares the asking price to the market median, and reuses
// the Phase 07 authenticity auto-check when the match is a card. Read-only — no
// data/ writes, no new tables. Mirrors backend ShopListingOut / ShopMatchOut /
// ShopDealOut / ShopAssessmentOut field-for-field. Honest empty states
// everywhere: `market`/`edge` are null when there are no sold comps (never a
// fabricated $0); `listing_unavailable`/`listing_not_found` are honest flags
// the UI branches on rather than synthesizing a listing; `caveat` always
// travels with the assessment so the guide-vs-verdict framing is shown.
// Authenticity is the existing Phase 07 shape (imported as-is, never redefined).

// One eBay listing the engine fetched. Every nullable column surfaces as
// null when the source omits it; `source` is always present (the backend never
// fabricates a default). `item_id` is the eBay item id extracted from the URL.
export interface ShopListing {
  item_id: string;
  title: string | null;
  price: number | null;
  currency: string | null;
  condition: string | null;
  listing_type: string | null;
  auction_end_at: string | null;
  seller: string | null;
  image_url: string | null;
  url: string | null;
  source: string;
}

// The catalog match for the listing. `kind === "none"` means no card or sealed
// product matched — the UI shows listing facts only (no deal, no authenticity).
// `confidence` is the matcher's own self-assessment; "low" is surfaced so the
// user can judge whether the match is worth trusting. Card fields are null when
// kind !== "card"; sealed fields are null when kind !== "sealed".
export interface ShopMatch {
  kind: "card" | "sealed" | "none";
  confidence: "high" | "low";
  card_id: string | null;
  card_name: string | null;
  card_number: string | null;
  card_rarity: string | null;
  set_name: string | null;
  sealed_slug: string | null;
  sealed_name: string | null;
}

// The deal assessment for the listing. `market`/`market_source`/
// `market_source_updated_at` are null when there are no sold comps — never a
// fabricated $0. `edge` (listing price minus market median) is null when market
// is null; `is_deal` is an honest boolean against the thresholds; a null edge is
// never a deal. `market_unavailable` (no listings key) vs `market_empty` (key
// set, 0 comps) mirror the sealed-deals honest flags. `min_abs`/`min_pct` are
// the thresholds the engine applied, echoed so the UI can label why.
export interface ShopDeal {
  market: number | null;
  market_source: string | null;
  market_source_updated_at: string | null;
  sold_comps_count: number;
  edge: number | null;
  is_deal: boolean;
  min_abs: number;
  min_pct: number;
  market_unavailable: boolean;
  market_empty: boolean;
}

// The GET /shop/assess?url=&limit= response. `listing_unavailable` is true when
// no listings provider key is configured (honest — no provider, never fake a
// listing); `listing_not_found` is true when the key is set but the URL did not
// resolve to a live eBay listing. `listing` is null in either case; `match` is
// always present (kind "none" when there was nothing to match). `deal` is null
// when match.kind === "none" (no catalog object to price against). `authenticity`
// is non-null only for card matches (sealed/none have no printed-number check).
// `caveat` always travels so the guide-not-verdict framing is shown.
export interface ShopAssessment {
  url: string;
  item_id: string | null;
  listing_unavailable: boolean;
  listing_not_found: boolean;
  listing: ShopListing | null;
  match: ShopMatch;
  deal: ShopDeal | null;
  authenticity: Authenticity | null;
  caveat: string;
}
