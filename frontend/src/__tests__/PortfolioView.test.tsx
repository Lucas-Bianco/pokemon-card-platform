import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import type { Portfolio, PortfolioItem, PriceHistory } from "../api/types";
import PortfolioView from "../components/PortfolioView";

function pricedItem(overrides: Partial<PortfolioItem> = {}): PortfolioItem {
  return {
    id: 1,
    card_id: "base1-4",
    card_name: "Charizard",
    set_id: "base1",
    set_name: "Base",
    variant: "holofoil",
    quantity: 1,
    acquired_price: 200.0,
    acquired_at: "2026-07-01T00:00:00Z",
    condition: null,
    notes: null,
    market_price: 250.0,
    market_source: "tcgplayer",
    market_source_updated_at: "2026/07/29",
    unrealized: 50.0,
    priced: true,
    ...overrides,
  };
}

function unpricedItem(overrides: Partial<PortfolioItem> = {}): PortfolioItem {
  return {
    ...pricedItem({
      id: 2,
      card_id: "base1-58",
      card_name: "Gyarados",
      acquired_price: null,
      acquired_at: null,
      market_price: null,
      market_source: null,
      market_source_updated_at: null,
      unrealized: null,
      priced: false,
    }),
    ...overrides,
  };
}

function portfolio(over: Partial<Portfolio> = {}): Portfolio {
  return {
    summary: {
      market_value: 250.0,
      cost_basis: 200.0,
      unrealized: 50.0,
      unpriced_items: 1,
      priced_items: 1,
      allocation: [
        { set_id: "base1", set_name: "Base", market_value: 250.0, cost_basis: 200.0, item_count: 2 },
      ],
      top_gainers: [pricedItem()],
      top_losers: [],
    },
    items: [pricedItem(), unpricedItem()],
    ...over,
  };
}

function stubFetch(body: Portfolio, history?: PriceHistory) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/portfolio")) {
      return { ok: true, status: 200, json: async () => body };
    }
    if (String(url).includes("/prices/history")) {
      return {
        ok: true,
        status: 200,
        json: async () => history ?? { card_id: "base1-4", variant: "holofoil", points: [] },
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("PortfolioView", () => {
  it("renders the summary grid with market value, cost basis, and unrealised P/L", async () => {
    stubFetch(portfolio());

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$250.00");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("$200.00");
    // Unrealised is +$50.00 with the up colouring — a gain, never missing data here.
    expect(text).toContain("+");
    expect(text).toContain("$50.00");
    expect(container.querySelector(".valuation .up")).not.toBeNull();
  });

  it("renders an em dash and the 'no purchase prices' note when cost basis is zero", async () => {
    stubFetch(
      portfolio({
        summary: {
          market_value: 250.0,
          cost_basis: 0,
          unrealized: 50.0,
          unpriced_items: 1,
          priced_items: 1,
          allocation: [],
          top_gainers: [],
          top_losers: [],
        },
        items: [unpricedItem()],
      }),
    );

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no purchase prices recorded/i);
    });
    expect(container.querySelector(".valuation .unknown")).not.toBeNull();
  });

  it("shows per-item market price and unrealised P/L in the holdings table", async () => {
    stubFetch(portfolio());

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.querySelector(".portfolio-table")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Charizard");
    expect(text).toContain("$250.00"); // market price for the priced item
  });

  it("renders an em dash and 'no market price' for an unpriced item, not $0.00", async () => {
    stubFetch(portfolio());

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Gyarados");
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/no market price/i);
    // The unpriced row's market cell is an em dash, not a dressed-up zero.
    expect(container.querySelectorAll(".portfolio-table .unpriced").length).toBeGreaterThan(0);
  });

  it("renders a History button per holding row", async () => {
    stubFetch(portfolio());

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.querySelector(".portfolio-table")).not.toBeNull();
    });
    const historyButtons = [...container.querySelectorAll("button")].filter((b) =>
      /history/i.test(b.textContent ?? ""),
    );
    expect(historyButtons.length).toBeGreaterThan(0);
  });

  it("renders the chart after clicking History and fetching price history", async () => {
    const history: PriceHistory = {
      card_id: "base1-4",
      variant: "holofoil",
      points: [
        {
          fetched_at: "2026-07-01T12:00:00Z",
          source: "tcgplayer",
          variant: "holofoil",
          market: 80.0,
          source_updated_at: "2026/07/01",
        },
        {
          fetched_at: "2026-07-29T12:00:00Z",
          source: "tcgplayer",
          variant: "holofoil",
          market: 100.0,
          source_updated_at: "2026/07/29",
        },
      ],
    };
    stubFetch(portfolio(), history);

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.querySelector(".portfolio-table")).not.toBeNull();
    });
    const historyButton = [...container.querySelectorAll("button")].find((b) =>
      /history/i.test(b.textContent ?? ""),
    );
    expect(historyButton).toBeDefined();

    fireEvent.click(historyButton as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".price-chart")).not.toBeNull();
    });
    expect(container.querySelector("polyline")).not.toBeNull();
  });
});