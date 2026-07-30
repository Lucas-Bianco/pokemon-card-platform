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

export interface RecognizeResponse {
  status: RecognitionStatus;
  confidence: number;
  visual_margin: number;
  card: CardSummary | null;
  price: Price | null;
  candidates: Candidate[];
  collector_number_read: string | null;
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
