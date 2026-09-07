import type { RecognitionStatus } from "../api/types";

export function formatMoney(value: number | null | undefined): string {
  // An em dash, not $0.00 — an unpriced card is unknown, not worthless. The backend
  // is deliberately conservative about this and the UI must not undo it. Note the
  // explicit null/undefined check: a genuine 0 is a real price.
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

export function formatStaleness(sourceUpdatedAt: string | null | undefined): string {
  if (!sourceUpdatedAt) return "date unknown";
  return `as of ${sourceUpdatedAt}`;
}

// Raw price-source slugs ("tcgplayer", "cardmarket", "ebay_sold") are opaque to a
// collector reading a figure. Map the known ones to a legible, descriptive label
// so every price wire says where it came from in plain language; an unrecognized
// slug (e.g. a graded-price source's proper name like "pkmnprices") is returned
// unchanged rather than coerced — it is already a name a collector recognizes, and
// inventing a label would obscure provenance. null/empty → "source unknown" so a
// price is never shown alongside a blank where its source should be.
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "source unknown";
  const s = source.trim().toLowerCase();
  if (!s) return "source unknown";
  if (
    s === "tcgplayer" ||
    s === "tcgplayer_via_ptcgo" ||
    s === "tcgplayer_via_pokemontcg"
  ) {
    return "TCGplayer market reference";
  }
  if (s === "cardmarket") return "Cardmarket aggregate";
  if (s === "ebay_sold" || s === "ebay") return "eBay sold comps";
  return source;
}

export function statusLabel(status: RecognitionStatus): string {
  switch (status) {
    case "confident":
      return "Identified";
    case "ambiguous":
      return "Not sure — pick one";
    case "not_found":
      return "No card found";
  }
}
