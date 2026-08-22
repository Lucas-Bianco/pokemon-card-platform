import type {
  AlertEvent,
  AlertType,
  Authenticity,
  BatchRecognizeResponse,
  CardSearchResult,
  CollectionItem,
  DealsResponse,
  Grader,
  GradingLabel,
  GradingUpside,
  ListingsResponse,
  Portfolio,
  Price,
  PriceHistory,
  PushSubscription,
  RecognizeResponse,
  Scan,
  SealedDealsResponse,
  SealedLedgerResponse,
  SealedPurchaseOut,
  SealedSoldCompsResponse,
  SetCompletion,
  SetProgress,
  SheetsSyncResult,
  SoldCompsResponse,
  Valuation,
  ValuationRefreshResult,
  Watch,
  WatchCreate,
  WatchPatch,
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

// Phase 4 bulk cataloger: detect + recognise N cards in one binder-page photo.
// Mirrors `recognize`'s FormData/expectJson/query-string style. `maxCards`
// defaults to 9 (a 3x3 binder page) and the backend clamps to [1, 18]. Each
// result in the response carries its own status/price/rectified_path — the
// caller logs each card via recordScan, threading batch_id + batch_index back.
export async function batchRecognize(
  image: Blob,
  variant = "normal",
  maxCards = 9,
): Promise<BatchRecognizeResponse> {
  const params = new URLSearchParams({ variant, max_cards: String(maxCards) });
  const body = new FormData();
  body.append("file", image, "page.jpg");

  return expectJson<BatchRecognizeResponse>(
    await fetch(`${BASE}/recognize/batch?${params}`, { method: "POST", body }),
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

export async function recordScan(
  image: Blob,
  result: RecognizeResponse,
  options?: {
    batch_id?: string;
    batch_index?: number;
    rectified_path?: string | null;
    variant?: string | null;
  },
): Promise<Scan> {
  const params = new URLSearchParams({ status: result.status });
  if (result.card) params.set("predicted_card_id", result.card.id);
  params.set("confidence", String(result.confidence));
  params.set("visual_margin", String(result.visual_margin));
  if (result.collector_number_read) {
    params.set("collector_number_read", result.collector_number_read);
  }
  // Phase 4: thread batch grouping + the rectified crop + variant through to
  // the scan_logs row. All optional — omitted (the default) leaves existing
  // single-card behaviour unchanged.
  if (options?.batch_id) params.set("batch_id", options.batch_id);
  if (options?.batch_index !== undefined) {
    params.set("batch_index", String(options.batch_index));
  }
  if (options?.rectified_path) params.set("rectified_path", options.rectified_path);
  if (options?.variant) params.set("variant", options.variant);
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

// The raw-vs-graded price spread (NOT a grade prediction). Mirrors
// getResolvedPrice: query-string variant, expectJson for the body.
export async function getGradingUpside(
  cardId: string,
  variant: string,
): Promise<GradingUpside> {
  const params = new URLSearchParams({ variant });
  return expectJson<GradingUpside>(
    await fetch(`${BASE}/cards/${cardId}/grading-upside?${params}`),
  );
}

// The label attached to a scan, or null when none exists yet. "No label yet"
// is the common case (most scans are never mailed in) and the backend signals
// it with 404 — distinct from a real error, so we swallow it to null rather
// than throwing, mirroring jsonOrNull's treatment of 204 for unpriced cards.
export async function getGradeLabel(scanId: number): Promise<GradingLabel | null> {
  const response = await fetch(`${BASE}/scans/${scanId}/grade-label`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return (await response.json()) as GradingLabel;
}

// Record the grade a user received back from PSA/CGC/BGS for this scan. The
// backend resolves card_id/variant from the scan itself (never the body), so
// the label always describes the card the scan identified — the body carries
// only grade, grader, cert_number, notes (matches GradingLabelIn in api.py).
export async function postGradeLabel(
  scanId: number,
  body: {
    grade: number;
    grader: Grader;
    cert_number?: string | null;
    notes?: string | null;
  },
): Promise<GradingLabel> {
  const response = await fetch(`${BASE}/scans/${scanId}/grade-label`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return expectJson<GradingLabel>(response);
}

// The honest counterfeit tool for one scan: the catalog-consistency auto-check
// (printed number vs catalog) plus the user-driven physical checklist. Never a
// fake/real verdict — see Authenticity in types.ts. Unlike getGradeLabel, a
// 404 here means the scan itself is unknown (a genuine error), so it throws
// rather than swallowing to null. The component surfaces the error honestly.
export async function getAuthenticity(scanId: number): Promise<Authenticity> {
  const response = await fetch(`${BASE}/scans/${scanId}/authenticity`);
  return expectJson<Authenticity>(response);
}

// Catalog search by name. The backend's GET /cards takes a `name` query param
// (min_length=1) and returns the top N CardOut rows ordered by name; we surface
// the subset the Browse list needs. Empty query is NOT sent — the backend
// requires min_length=1, so the caller shows a hint instead.
export async function searchCards(q: string, limit = 25): Promise<CardSearchResult[]> {
  const params = new URLSearchParams({ name: q, limit: String(limit) });
  return expectJson<CardSearchResult[]>(
    await fetch(`${BASE}/cards?${params}`),
  );
}

// Fetch a single card by id. Mirrors GET /cards/{id} → CardOut (typed here as
// CardSearchResult, which is the same shape subset CardDetail renders).
export async function getCard(cardId: string): Promise<CardSearchResult> {
  return expectJson<CardSearchResult>(await fetch(`${BASE}/cards/${cardId}`));
}

// Phase 06 — set completion. All server-side: the client never resolves prices
// itself. getSets returns per-set owned/total progress (no price fan-out);
// getSetCompletion returns the full checklist + summary for one set.
export async function getSets(q?: string, limit = 50): Promise<SetProgress[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q && q.trim()) params.set("q", q.trim());
  return expectJson<SetProgress[]>(await fetch(`${BASE}/sets?${params}`));
}

export async function getSetCompletion(setId: string): Promise<SetCompletion> {
  return expectJson<SetCompletion>(
    await fetch(`${BASE}/sets/${encodeURIComponent(setId)}`),
  );
}

// Refresh + return the latest marketplace listings for a card/variant. The
// backend returns {listings, listings_unavailable}; an empty key means
// listings_unavailable=true (never fabricated listings).
export async function refreshListings(
  cardId: string,
  variant?: string,
): Promise<ListingsResponse> {
  const params = new URLSearchParams();
  if (variant) params.set("variant", variant);
  return expectJson<ListingsResponse>(
    await fetch(`${BASE}/cards/${cardId}/listings?${params}`, { method: "POST" }),
  );
}

// The unread alert count for the Alerts tab badge. Trivial now so the badge
// works in T6; T7 wires the live feed. Returns {count} → number.
export async function getUnreadCount(): Promise<number> {
  const response = await fetch(`${BASE}/alerts/unread-count`);
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  const body = (await response.json()) as { count: number };
  return body.count;
}

// Like expectJson, but on a non-ok response reads the body and surfaces the
// backend's `detail` message (FastAPI's validation error shape) in the thrown
// Error's message. Used by createWatch so a 422 ("target_price is required
// for alert_type 'price_target'") reaches the sheet as a helpful string
// rather than a bare "request failed: 422".
async function expectJsonOrDetail<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `request failed: ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // Body wasn't JSON (or already consumed) — keep the status message.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

// ----- Watchlist ---------------------------------------------------------
// Phase 3c alert subscriptions. Filters are exact-match (card_id, active);
// ordered newest first by the backend. Mirrors the GET/POST/PATCH/DELETE
// /watchlist endpoints.

export async function getWatches(
  cardId?: string,
  active?: boolean,
): Promise<Watch[]> {
  const params = new URLSearchParams();
  if (cardId) params.set("card_id", cardId);
  if (active !== undefined) params.set("active", String(active));
  const qs = params.toString();
  return expectJson<Watch[]>(
    await fetch(qs ? `${BASE}/watchlist?${qs}` : `${BASE}/watchlist`),
  );
}

export async function createWatch(payload: WatchCreate): Promise<Watch> {
  const response = await fetch(`${BASE}/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  // 422 from the backend carries a useful detail string (e.g. "target_price
  // is required for alert_type 'price_target'"). Surface it so the sheet can
  // show it instead of a generic status code.
  return expectJsonOrDetail<Watch>(response);
}

export async function patchWatch(id: number, patch: WatchPatch): Promise<Watch> {
  const response = await fetch(`${BASE}/watchlist/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return expectJson<Watch>(response);
}

export async function deleteWatch(id: number): Promise<void> {
  const response = await fetch(`${BASE}/watchlist/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
}

// ----- Alerts feed -------------------------------------------------------
// The engine fires AlertEvents; this layer reads them and flips read_at.

export async function getAlerts(
  opts?: { unread?: boolean; limit?: number; offset?: number },
): Promise<AlertEvent[]> {
  const params = new URLSearchParams();
  if (opts?.unread !== undefined) params.set("unread", String(opts.unread));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return expectJson<AlertEvent[]>(
    await fetch(qs ? `${BASE}/alerts?${qs}` : `${BASE}/alerts`),
  );
}

export async function markAlertRead(id: number): Promise<AlertEvent> {
  return expectJson<AlertEvent>(
    await fetch(`${BASE}/alerts/${id}`, { method: "PATCH" }),
  );
}

export async function readAllAlerts(): Promise<{ updated: number }> {
  return expectJson<{ updated: number }>(
    await fetch(`${BASE}/alerts/read-all`, { method: "POST" }),
  );
}

// ----- Web Push ----------------------------------------------------------
// VAPID public key + subscribe/unsubscribe. An empty public_key means the
// server has no VAPID config — the frontend treats that as "push not
// configured" and never fakes a subscription.

export async function getVapidPublic(): Promise<string> {
  const response = await fetch(`${BASE}/push/vapid-public`);
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  const body = (await response.json()) as { public_key: string };
  return body.public_key;
}

export async function subscribePush(
  sub: PushSubscription,
): Promise<{ id: number }> {
  const response = await fetch(`${BASE}/push/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
  });
  return expectJson<{ id: number }>(response);
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  const params = new URLSearchParams({ endpoint });
  const response = await fetch(`${BASE}/push/subscribe?${params}`, {
    method: "DELETE",
  });
  // 404 means the server holds no such subscription — which is the state this
  // call exists to reach, so it is success, not failure. Turning push off must
  // not report an error just because the row was already gone (a stale browser
  // subscription, or a second tab that unsubscribed first). Any other non-OK
  // status is a real failure and still throws.
  if (!response.ok && response.status !== 404) {
    throw new Error(`request failed: ${response.status}`);
  }
}

// The alert-type set the watchlist accepts. Mirrors the backend's
// _ALERT_TYPES so the sheet's picker never offers a value the endpoint would
// reject.
export const ALERT_TYPES: AlertType[] = [
  "restock",
  "new_listing",
  "price_target",
  "auction_ending",
  "drop_time",
  "deal",
];

// ----- Deals feed --------------------------------------------------------
// Phase 05 deal sniper. Rip-vs-flip assessments per card, or a cross-card feed
// across the user's watched cards. Mirrors the GET /cards/{id}/deals and
// GET /deals endpoints. expectJsonOrDetail so a 422 (e.g. unknown card) surfaces
// the backend's detail message rather than a bare status. Empty `variant`
// is omitted (not sent as "normal") — the backend assesses the default variant.

export async function getDeals(cardId: string, variant?: string): Promise<DealsResponse> {
  const q = variant ? `?variant=${encodeURIComponent(variant)}` : "";
  return expectJsonOrDetail<DealsResponse>(
    await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/deals${q}`),
  );
}

export async function getDealsFeed(cardIds?: string[], limit = 20): Promise<DealsResponse> {
  const params = new URLSearchParams();
  if (cardIds && cardIds.length) params.set("card_ids", cardIds.join(","));
  params.set("limit", String(limit));
  return expectJsonOrDetail<DealsResponse>(await fetch(`${BASE}/deals?${params}`));
}

// ----- Sold comps --------------------------------------------------------
// Phase 05b deal-alerts evidence: recent eBay sold comps backing a card's raw
// market price. Sold comps are EVIDENCE ("market $120 because these 3 just
// sold at $118/$121/$119"), never a price target. Mirrors GET
// /cards/{id}/sold-comps?variant=&limit=. Empty `variant` is sent as "" (the
// backend resolves the default variant) and `limit` defaults to 3 (the panel
// shows a tight evidence cluster, not a long feed).
export async function getSoldComps(
  cardId: string,
  variant: string,
  limit = 3,
): Promise<SoldCompsResponse> {
  const params = new URLSearchParams({ variant: variant || "", limit: String(limit) });
  return expectJson<SoldCompsResponse>(
    await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/sold-comps?${params}`),
  );
}

// ----- Sealed deals ------------------------------------------------------
// Phase 05c sealed-product flip-edge. Query-keyed (not card-keyed): a sealed
// product (booster box, ETB, collection box, pack) is searched by free text on
// eBay via the same Finding API + App ID as listings — no separate key.
// Mirrors GET /deals style (URLSearchParams + expectJsonOrDetail so a 422 from
// a whitespace/short/missing query surfaces the backend's detail message rather
// than a bare status). Honest empty states: no key -> listings_unavailable;
// key set but no listings -> listings_empty; no sold comps -> sealed_market
// null -> every flip_edge null (never $0).
export async function getSealedDeals(
  query: string,
  limit = 20,
): Promise<SealedDealsResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return expectJsonOrDetail<SealedDealsResponse>(
    await fetch(`${BASE}/sealed/deals?${params}`),
  );
}

// ----- Sealed proof of sales ---------------------------------------------
// Phase 16 — the individual recently-sold eBay listings behind the median
// sealed_market (proven sales, not a listed estimate). Query-keyed like
// getSealedDeals; `limit` defaults to 6 (a tight evidence cluster, matching the
// backend default). Mirrors getSealedDeals (expectJsonOrDetail so a 422 from a
// short/whitespace query surfaces the backend detail). Honest empty flags are
// consumed by the caller, not collapsed here.
export async function getSealedSoldComps(
  query: string,
  limit = 6,
): Promise<SealedSoldCompsResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return expectJsonOrDetail<SealedSoldCompsResponse>(
    await fetch(`${BASE}/sealed/sold-comps?${params}`),
  );
}

// ----- Sealed ledger -----------------------------------------------------
// Phase 05d sealed-purchase ledger. The user logs sealed boxes/packs they
// bought (query-keyed, like sealed deals); the backend values them against the
// eBay sold-comps median. Mirrors getSealedDeals (expectJsonOrDetail so a 422
// from a short/missing query surfaces the backend's detail) for the GET,
// addToCollection (POST JSON) for logging, and removeFromCollection (DELETE)
// for removal. Honest empty: an unvalued purchase renders "—" via formatMoney,
// never $0.00.

export async function getSealedLedger(): Promise<SealedLedgerResponse> {
  return expectJsonOrDetail<SealedLedgerResponse>(
    await fetch(`${BASE}/sealed/ledger`),
  );
}

export async function logSealedPurchase(body: {
  query: string;
  quantity?: number;
  cost_per_unit: number;
  product_type?: string | null;
  source?: string | null;
  listing_url?: string | null;
  notes?: string | null;
}): Promise<SealedPurchaseOut> {
  const response = await fetch(`${BASE}/sealed/ledger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json();
}

export async function deleteSealedPurchase(purchaseId: number): Promise<void> {
  const response = await fetch(`${BASE}/sealed/ledger/${purchaseId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
}

export async function valuateSealedLedger(): Promise<ValuationRefreshResult> {
  return expectJsonOrDetail<ValuationRefreshResult>(
    await fetch(`${BASE}/sealed/ledger/valuate`, { method: "POST" }),
  );
}

// Sync the sealed ledger to Google Sheets. Mirrors valuateSealedLedger (POST +
// expectJsonOrDetail). The backend returns `synced: false, reason:
// "not_configured"` when OAuth/sheet aren't set up — no network call, no raise —
// so the UI shows honest setup instructions rather than fabricating success.
export async function syncSealedLedger(): Promise<SheetsSyncResult> {
  return expectJsonOrDetail<SheetsSyncResult>(
    await fetch(`${BASE}/sealed/ledger/sync`, { method: "POST" }),
  );
}
