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
