import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import Deals from "../components/Deals";
import type { DealAssessment, DealsResponse } from "../api/types";

// A complete DealAssessment with sensible defaults; tests override the fields
// that exercise each honest-empty branch. Every nullable column has a real
// value here so the "ranked deal" test asserts the full chip set, and each
// empty-state test only flips the relevant fields to null.
function baseDeal(over: Partial<DealAssessment> = {}): DealAssessment {
  return {
    listing_id: "L1",
    title: "Charizard ex 215",
    listing_price: 80.0,
    currency: "USD",
    url: "https://ebay.com/1",
    condition: "Raw",
    listing_type: "fixed_price",
    auction_end_at: null,
    fetched_at: "2026-08-02T00:00:00Z",
    raw_market: { price: 120.0, source: "tcgplayer", source_updated_at: "2026-08-01" },
    rip_edge: 40.0,
    psa9_comp: { price: 150.0, source: "pkmnprices", source_updated_at: "2026-08-01" },
    psa10_comp: { price: 200.0, source: "pkmnprices", source_updated_at: "2026-08-01" },
    flip_edge_to_9: 25.0,
    flip_edge_to_10: 95.0,
    grading_fee: 25.0,
    deal_score: 95.0,
    is_rip: true,
    is_flip: true,
    ...over,
  };
}

function baseResponse(over: Partial<DealsResponse> = {}): DealsResponse {
  return {
    card_id: null,
    variant: null,
    listings_unavailable: false,
    listings_empty: false,
    deals: [],
    thresholds: { deal_rip_min_abs: 2.0, deal_rip_min_pct: 0.1, deal_flip_min_abs: 20.0 },
    ...over,
  };
}

// Routed fetch stub. The Deals screen mounts and, with the watched toggle ON
// and no card picked, calls getDealsFeed() → GET /deals. Card search
// (GET /cards?name=) returns [] so the search box never interferes. Per-card
// deals (GET /cards/{id}/deals) return the per-card body when a test selects
// one. Mirrors the AlertsFeed/CardDetail stub idiom.
function stubFetch(opts: { feed?: DealsResponse; card?: DealsResponse | null }) {
  const feed = opts.feed ?? baseResponse();
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    // Catalog search — empty results keep the search box out of the way.
    if (u.includes("/cards?") || u.includes("/cards&")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    // Per-card deals.
    if (u.match(/\/cards\/[^/]+\/deals/)) {
      if (opts.card === null) return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => opts.card ?? feed };
    }
    // Cross-card feed (the default mount target).
    if (u.includes("/deals")) {
      return { ok: true, status: 200, json: async () => feed };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("Deals", () => {
  it("renders a ranked deal with rip + flip chips and the investigate caveat", async () => {
    const deal = baseDeal();
    stubFetch({ feed: baseResponse({ deals: [deal] }) });

    const { container } = render(<Deals />);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Charizard ex 215");
    expect(container.querySelector(".deal-chip.rip")).not.toBeNull();
    expect(container.querySelector(".deal-chip.flip")).not.toBeNull();
    expect(text).toMatch(/investigate before buying/i);
  });

  it("listings_unavailable shows the set-a-key empty state", async () => {
    stubFetch({ feed: baseResponse({ listings_unavailable: true, deals: [] }) });

    const { container } = render(<Deals />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/Set a listings source key/i);
    });
    expect(container.querySelector(".deal-card")).toBeNull();
  });

  it("listings_empty shows no-active-listings", async () => {
    stubFetch({ feed: baseResponse({ listings_empty: true, deals: [] }) });

    const { container } = render(<Deals />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/No active listings/i);
    });
    expect(container.querySelector(".deal-card")).toBeNull();
  });

  it("no raw market shows an em dash rip edge and 'no market price'", async () => {
    const deal = baseDeal({
      raw_market: null,
      rip_edge: null,
      psa10_comp: { price: 200.0, source: "pkmnprices", source_updated_at: "2026-08-01" },
      flip_edge_to_10: 50.0,
    });
    stubFetch({ feed: baseResponse({ deals: [deal] }) });

    const { container } = render(<Deals />);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/no market price/i);
    // Rip edge renders an em dash, never $0.00.
    const ripEdge = container.querySelector(".deal-rip-edge");
    expect(ripEdge).not.toBeNull();
    expect(ripEdge!.textContent ?? "").toContain("—");
  });

  it("no graded comps shows em dash flip edges and no flip chip", async () => {
    const deal = baseDeal({
      psa9_comp: null,
      psa10_comp: null,
      flip_edge_to_9: null,
      flip_edge_to_10: null,
      raw_market: { price: 120.0, source: "tcgplayer", source_updated_at: "2026-08-01" },
      rip_edge: 5.0,
      is_flip: false,
    });
    stubFetch({ feed: baseResponse({ deals: [deal] }) });

    const { container } = render(<Deals />);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    const flip10 = container.querySelector(".deal-flip-10");
    const flip9 = container.querySelector(".deal-flip-9");
    expect(flip10).not.toBeNull();
    expect(flip9).not.toBeNull();
    expect(flip10!.textContent ?? "").toContain("—");
    expect(flip9!.textContent ?? "").toContain("—");
    // No flip chip when is_flip is false.
    expect(container.querySelector(".deal-chip.flip")).toBeNull();
  });
});