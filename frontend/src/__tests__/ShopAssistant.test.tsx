import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";

import ShopAssistant from "../components/ShopAssistant";
import type { ShopAssessment } from "../api/types";

// A complete ShopAssessment with sensible defaults for a sealed happy path;
// tests override the fields that exercise each branch. Mirrors the
// SealedDeals.test.tsx baseDeal/baseResponse idiom: every nullable column has a
// real value here so the "happy" test asserts the full chip set, and each
// empty-state test only flips the relevant fields.
function assessmentBody(over: Partial<ShopAssessment> = {}): ShopAssessment {
  return {
    url: "https://www.ebay.com/itm/123",
    item_id: "123",
    listing_unavailable: false,
    listing_not_found: false,
    listing: {
      item_id: "123",
      title: "SV Booster Box",
      price: 95.0,
      currency: "USD",
      condition: "New",
      listing_type: "fixed_price",
      auction_end_at: null,
      seller: "power-seller",
      image_url: "https://img.example/x.jpg",
      url: "https://www.ebay.com/itm/123",
      source: "ebay",
    },
    match: {
      kind: "sealed",
      confidence: "high",
      card_id: null,
      card_name: null,
      card_number: null,
      card_rarity: null,
      set_name: null,
      sealed_slug: "sv-booster-box",
      sealed_name: "Scarlet & Violet Booster Box",
    },
    deal: {
      market: 120.0,
      market_source: "ebay",
      market_source_updated_at: "2026-08-20",
      sold_comps_count: 5,
      edge: -25.0,
      is_deal: false,
      min_abs: 20.0,
      min_pct: 0.05,
      market_unavailable: false,
      market_empty: false,
    },
    authenticity: null,
    caveat: "A guide, not a verdict. Assess before you buy.",
    ...over,
  };
}

// Routed fetch stub. ShopAssistant only fetches after the user submits the URL
// form (GET /shop/assess?url=&limit=). Mirrors the SealedDeals stub idiom: a
// single vi.fn routed by URL substring, installed via stubGlobal. Returns the
// canned assessment for /shop/assess, 404 for anything else.
function stubFetch(body: ShopAssessment, status = 200) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/shop/assess?")) {
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

// Helper: type a URL into the search box and submit the form. Returns the
// container so each case can assert against the rendered output.
function submitUrl(container: HTMLElement, value: string) {
  const input = container.querySelector(
    "input[type=search]",
  ) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  const form = container.querySelector("form") as HTMLFormElement;
  fireEvent.submit(form);
}

describe("ShopAssistant", () => {
  it("happy sealed: renders listing + deal (edge<0, is_deal false) + the sealed match line", async () => {
    stubFetch(assessmentBody());
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent).toContain("Matched sealed product");
    });
    expect(container.textContent).toContain("Scarlet & Violet Booster Box");
    // Listing facts render.
    expect(container.querySelector(".shop-listing")).toBeTruthy();
    expect(container.textContent).toContain("View on eBay");
    // Deal block present with the honest market row.
    expect(container.querySelector(".shop-deal")).toBeTruthy();
    expect(container.textContent).toContain("$120.00");
  });

  it("happy card: renders listing + authenticity (consistency match) + the card match line", async () => {
    stubFetch(
      assessmentBody({
        match: {
          kind: "card",
          confidence: "high",
          card_id: "base1-4",
          card_name: "Charizard",
          card_number: "4",
          card_rarity: "Rare Holo",
          set_name: "Base",
          sealed_slug: null,
          sealed_name: null,
        },
        authenticity: {
          caveat: "A guide, not a verdict. Zero confirmed-counterfeit samples.",
          consistency: {
            printed_number: "4",
            catalog_number: "4",
            card_id: "base1-4",
            card_name: "Charizard",
            match: "match",
            note: "The printed number (4) matches the catalog for Charizard.",
          },
          checklist: [
            {
              id: "rosette",
              title: "Rosette / dot pattern",
              what_to_check: "Under a loupe, real cards show a rosette.",
              caveat: "Needs a loupe.",
              applies: true,
            },
          ],
        },
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent).toContain("Matched card");
    });
    expect(container.textContent).toContain("Charizard (Base)");
    // Inlined authenticity block renders the match status.
    expect(container.querySelector(".authenticity-consistency")).toBeTruthy();
    expect(container.querySelector(".consistency-status")?.textContent).toContain(
      "Printed number matches",
    );
  });

  it("deal-under: edge<0 with is_deal true shows the deal verdict + .deal-delta-under", async () => {
    stubFetch(
      assessmentBody({
        deal: {
          market: 120.0,
          market_source: "ebay",
          market_source_updated_at: "2026-08-20",
          sold_comps_count: 5,
          edge: -25.0,
          is_deal: true,
          min_abs: 20.0,
          min_pct: 0.05,
          market_unavailable: false,
          market_empty: false,
        },
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent).toContain("Below market — looks like a deal");
    });
    const delta = container.querySelector(".deal-delta");
    expect(delta?.classList.contains("deal-delta-under")).toBe(true);
    expect(delta?.classList.contains("deal-delta-over")).toBe(false);
  });

  it("no-match: kind none + deal null shows the no-match line and no deal block", async () => {
    stubFetch(
      assessmentBody({
        match: {
          kind: "none",
          confidence: "low",
          card_id: null,
          card_name: null,
          card_number: null,
          card_rarity: null,
          set_name: null,
          sealed_slug: null,
          sealed_name: null,
        },
        deal: null,
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent).toContain("Couldn't match this listing");
    });
    expect(container.querySelector(".shop-deal")).toBeNull();
    // Still shows the listing facts (not a missing-listing state).
    expect(container.querySelector(".shop-listing")).toBeTruthy();
  });

  it("listing_unavailable: shows the listings-key message and no fabricated market figure", async () => {
    stubFetch(
      assessmentBody({
        listing_unavailable: true,
        listing: null,
        match: {
          kind: "none",
          confidence: "low",
          card_id: null,
          card_name: null,
          card_number: null,
          card_rarity: null,
          set_name: null,
          sealed_slug: null,
          sealed_name: null,
        },
        deal: {
          market: null,
          market_source: null,
          market_source_updated_at: null,
          sold_comps_count: 0,
          edge: null,
          is_deal: false,
          min_abs: 20.0,
          min_pct: 0.05,
          market_unavailable: true,
          market_empty: false,
        },
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent?.toLowerCase()).toContain("set a listings key");
    });
    // Honest empty: never a fabricated $0.00.
    expect(container.textContent).not.toContain("$0.00");
    expect(container.querySelector(".shop-listing")).toBeNull();
  });

  it("listing_not_found: shows the couldn't-fetch message", async () => {
    stubFetch(
      assessmentBody({
        listing_not_found: true,
        listing: null,
        match: {
          kind: "none",
          confidence: "low",
          card_id: null,
          card_name: null,
          card_number: null,
          card_rarity: null,
          set_name: null,
          sealed_slug: null,
          sealed_name: null,
        },
        deal: null,
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.textContent).toContain("Couldn't fetch this listing");
    });
  });

  it("authenticity unread: card match with consistency unread renders without crashing", async () => {
    stubFetch(
      assessmentBody({
        match: {
          kind: "card",
          confidence: "low",
          card_id: "sv9-35",
          card_name: "Sprigatito",
          card_number: "35",
          card_rarity: "Common",
          set_name: "Paldea Evolved",
          sealed_slug: null,
          sealed_name: null,
        },
        authenticity: {
          caveat: "A guide, not a verdict.",
          consistency: {
            printed_number: null,
            catalog_number: "35",
            card_id: "sv9-35",
            card_name: "Sprigatito",
            match: "unread",
            note: "Could not read the printed number from this listing image.",
          },
          checklist: [
            {
              id: "rosette",
              title: "Rosette / dot pattern",
              what_to_check: "Under a loupe, real cards show a rosette.",
              caveat: "Needs a loupe.",
              applies: true,
            },
          ],
        },
      }),
    );
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "https://www.ebay.com/itm/123");
    await waitFor(() => {
      expect(container.querySelector(".consistency-status")?.textContent).toContain(
        "Could not read",
      );
    });
    // Renders the checklist without crashing.
    expect(container.querySelectorAll(".checklist-item").length).toBeGreaterThanOrEqual(1);
  });

  it("blank/short URL submit: makes no assess call and shows the error message", async () => {
    const spy = stubFetch(assessmentBody());
    const { container } = render(<ShopAssistant />);
    submitUrl(container, "abc");
    // No fetch was made to the assess endpoint.
    const assessCalls = spy.mock.calls.filter((c) =>
      String(c[0]).includes("/shop/assess"),
    );
    expect(assessCalls).toHaveLength(0);
    expect(container.textContent).toContain("Paste a full eBay listing URL.");
  });
});