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
