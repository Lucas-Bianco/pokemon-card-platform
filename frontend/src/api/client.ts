import type {
  CollectionItem,
  Portfolio,
  Price,
  PriceHistory,
  RecognizeResponse,
  Scan,
  Valuation,
} from "./types";

// Always relative: the Vite dev server proxies /api to the backend. Calling the
// backend's origin directly from this HTTPS page would be mixed content and blocked.
const BASE = "/api";

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

/** 204 means "no price", which is a normal state rather than an error. */
async function jsonOrNull<T>(response: Response): Promise<T | null> {
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function recognize(
  image: Blob,
  options: { rectify?: boolean; variant?: string; corners?: [number, number][] },
): Promise<RecognizeResponse> {
  const params = new URLSearchParams({
    rectify: String(options.rectify ?? true),
    variant: options.variant ?? "normal",
  });
  // Hand-placed corners, in the source image's pixel space — the server rectifies
  // against the original, so the caller converts from its own display scale first.
  if (options.corners) {
    params.set("corners", options.corners.flat().join(","));
  }
  const body = new FormData();
  body.append("file", image, "scan.jpg");

  return expectJson<RecognizeResponse>(
    await fetch(`${BASE}/recognize?${params}`, { method: "POST", body }),
  );
}

export async function getResolvedPrice(cardId: string, variant: string): Promise<Price | null> {
  const params = new URLSearchParams({ variant });
  return jsonOrNull<Price>(await fetch(`${BASE}/cards/${cardId}/price?${params}`));
}

export async function refreshPrice(cardId: string, variant: string): Promise<Price | null> {
  const params = new URLSearchParams({ variant });
  return jsonOrNull<Price>(
    await fetch(`${BASE}/cards/${cardId}/prices/refresh?${params}`, { method: "POST" }),
  );
}

export async function recordScan(image: Blob, result: RecognizeResponse): Promise<Scan> {
  const params = new URLSearchParams({ status: result.status });
  if (result.card) params.set("predicted_card_id", result.card.id);
  params.set("confidence", String(result.confidence));
  params.set("visual_margin", String(result.visual_margin));
  if (result.collector_number_read) {
    params.set("collector_number_read", result.collector_number_read);
  }
  const body = new FormData();
  body.append("file", image, "scan.jpg");

  return expectJson<Scan>(await fetch(`${BASE}/scans?${params}`, { method: "POST", body }));
}

export async function confirmScan(scanId: number): Promise<Scan> {
  return expectJson<Scan>(await fetch(`${BASE}/scans/${scanId}/confirm`, { method: "POST" }));
}

export async function correctScan(scanId: number, cardId: string): Promise<Scan> {
  const params = new URLSearchParams({ card_id: cardId });
  return expectJson<Scan>(
    await fetch(`${BASE}/scans/${scanId}/correct?${params}`, { method: "POST" }),
  );
}

export async function getCollection(): Promise<CollectionItem[]> {
  return expectJson<CollectionItem[]>(await fetch(`${BASE}/collection`));
}

export async function getValuation(): Promise<Valuation> {
  return expectJson<Valuation>(await fetch(`${BASE}/collection/valuation`));
}

export async function addToCollection(
  cardId: string,
  variant: string,
  acquiredPrice?: number | null,
): Promise<void> {
  // acquired_price is what makes profit/loss possible later. Omitted rather than sent
  // as 0 when unknown: the backend counts an item with no cost basis as contributing
  // nothing to cost, whereas a literal 0 would claim the card was free.
  const body: Record<string, unknown> = { card_id: cardId, variant, quantity: 1 };
  if (acquiredPrice !== undefined && acquiredPrice !== null && !Number.isNaN(acquiredPrice)) {
    body.acquired_price = acquiredPrice;
  }
  const response = await fetch(`${BASE}/collection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
}

export async function getPortfolio(): Promise<Portfolio> {
  // Priced holdings + summary in one round trip; all valuation is server-side, so the
  // client never resolves 'the latest price' itself.
  return expectJson<Portfolio>(await fetch(`${BASE}/collection/portfolio`));
}

export async function patchCollectionItem(
  id: number,
  update: {
    acquired_price?: number | null;
    acquired_at?: string | null;
    condition?: string | null;
    notes?: string | null;
  },
): Promise<CollectionItem> {
  const response = await fetch(`${BASE}/collection/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as CollectionItem;
}

export async function removeFromCollection(
  cardId: string,
  variant: string,
  quantity = 1,
): Promise<void> {
  const params = new URLSearchParams({
    card_id: cardId,
    variant,
    quantity: String(quantity),
  });
  const response = await fetch(`${BASE}/collection?${params}`, { method: "DELETE" });
  // 204 covers both a real removal and a no-op (nothing held); only a real error throws.
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
}

export async function getPriceHistory(
  cardId: string,
  variant: string,
  days?: number,
): Promise<PriceHistory> {
  const params = new URLSearchParams({ variant });
  if (days) {
    params.set("days", String(days));
  }
  return expectJson<PriceHistory>(
    await fetch(`${BASE}/cards/${cardId}/prices/history?${params}`),
  );
}
