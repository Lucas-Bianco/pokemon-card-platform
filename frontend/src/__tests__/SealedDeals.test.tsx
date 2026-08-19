import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import SealedDeals from "../components/SealedDeals";
import type { SealedDealAssessment, SealedDealsResponse } from "../api/types";

// A complete SealedDealAssessment with sensible defaults; tests override the
// fields that exercise each honest-empty branch. Mirrors the Deals.test.tsx
// baseDeal/baseResponse idiom: every nullable column has a real value here so
// the "ranked deal" test asserts the full chip set, and each empty-state test
// only flips the relevant fields to null.
function baseDeal(over: Partial<SealedDealAssessment> = {}): SealedDealAssessment {
  return {
    query: "scarlet violet booster box",
    listing_id: "1",
    title: "SV Booster Box",
    listing_price: 95.0,
    currency: "USD",
    url: "https://ebay.com/1",
    condition: "New",
    listing_type: "fixed_price",
    auction_end_at: null,
    fetched_at: "2026-08-19T00:00:00Z",
    sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
    flip_edge: 25.0,
    deal_score: 25.0,
    is_flip: true,
    ...over,
  };
}

function baseResponse(over: Partial<SealedDealsResponse> = {}): SealedDealsResponse {
  return {
    query: "scarlet violet booster box",
    limit: 20,
    listings_unavailable: false,
    listings_empty: false,
    comps_unavailable: false,
    comps_empty: false,
    sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
    deals: [],
    thresholds: { sealed_flip_min_abs: 20.0, sealed_flip_min_pct: 0.05 },
    ...over,
  };
}

// Routed fetch stub. The SealedDeals screen only fetches after the user submits
// the search form (GET /sealed/deals?q=&limit=). Mirrors the Deals/Browse stub
// idiom: a single vi.fn routed by URL substring, installed via stubGlobal.
function stubFetch(body: SealedDealsResponse, status = 200) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/sealed/deals")) {
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("SealedDeals", () => {
  it("renders the search box and a Find button", () => {
    stubFetch(baseResponse());
    const { container } = render(<SealedDeals />);

    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.placeholder).toMatch(/sealed product/i);
    const btn = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(btn).not.toBeNull();
    expect(btn.textContent ?? "").toMatch(/find/i);
  });

  it("fetches and shows ranked flip-edge deals with listing price + flip edge", async () => {
    const deal = baseDeal();
    stubFetch(baseResponse({ deals: [deal] }));

    const { container } = render(<SealedDeals />);
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "scarlet violet booster box" } });
    fireEvent.click(container.querySelector('button[type="submit"]') as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("SV Booster Box");
    // Listing price renders as $95.00, never a fabricated $0.00.
    expect(text).toMatch(/\$95\.00/);
    // Flip edge renders as $25.00.
    expect(text).toMatch(/\$25\.00/);
    // Flip chip present because is_flip is true (reuses .deal-chip.flip).
    expect(container.querySelector(".deal-chip.flip")).not.toBeNull();
  });

  it("shows an honest 'set a key' empty state when listings_unavailable", async () => {
    stubFetch(
      baseResponse({
        listings_unavailable: true,
        listings_empty: false,
        comps_unavailable: true,
        comps_empty: false,
        sealed_market: null,
        deals: [],
      }),
    );

    const { container } = render(<SealedDeals />);
    fireEvent.change(container.querySelector('input[type="search"]') as HTMLInputElement, {
      target: { value: "booster box" },
    });
    fireEvent.click(container.querySelector('button[type="submit"]') as HTMLButtonElement);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set.*CARDPLATFORM_LISTINGS_API_KEY|ebay app id/i);
    });
    expect(container.querySelector(".deal-card")).toBeNull();
  });

  it("shows an honest 'no sold comps / market price' state when sealed_market is null", async () => {
    // Listings exist (key set, listings returned) but no sold comps -> market
    // is null and every flip edge is null (honest, never $0).
    const deal = baseDeal({
      sealed_market: null,
      flip_edge: null,
      deal_score: null,
      is_flip: false,
    });
    stubFetch(
      baseResponse({
        comps_empty: true,
        sealed_market: null,
        deals: [deal],
      }),
    );

    const { container } = render(<SealedDeals />);
    fireEvent.change(container.querySelector('input[type="search"]') as HTMLInputElement, {
      target: { value: "booster box" },
    });
    fireEvent.click(container.querySelector('button[type="submit"]') as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    expect(container.textContent ?? "").toMatch(/no.*sold.*comp|market price/i);
    // Flip edge renders as an em dash, never a fabricated $0.00.
    expect(container.textContent ?? "").not.toMatch(/\$0\.00/);
  });

  it("never renders a fabricated $0.00 flip edge", async () => {
    const deal = baseDeal({
      sealed_market: null,
      flip_edge: null,
      deal_score: null,
      is_flip: false,
    });
    stubFetch(baseResponse({ sealed_market: null, deals: [deal] }));

    const { container } = render(<SealedDeals />);
    fireEvent.change(container.querySelector('input[type="search"]') as HTMLInputElement, {
      target: { value: "box" },
    });
    fireEvent.click(container.querySelector('button[type="submit"]') as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".deal-card")).not.toBeNull();
    });
    expect(container.textContent ?? "").not.toMatch(/\$0\.00/);
  });
});
