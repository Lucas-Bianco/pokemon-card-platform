import type { Price, RecognizeResponse, Scan } from "./types";

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

export async function addToCollection(cardId: string, variant: string): Promise<void> {
  const response = await fetch(`${BASE}/collection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card_id: cardId, variant, quantity: 1 }),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
}
