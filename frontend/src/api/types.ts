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
