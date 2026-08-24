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
  const insurance = {
    conservative: 90.0,
    median: 100.0,
    aggressive: 120.0,
    priced_items: 1,
    unpriced_items: 1,
    schedule: [
      {
        card_id: "base1-4",
        card_name: "Charizard",
        set_name: "Base",
        variant: "holofoil",
        quantity: 1,
        low: 90.0,
        market: 100.0,
        high: 120.0,
        source: "tcgplayer",
        source_updated_at: "2026/07/29",
        priced: true,
      },
    ],
    caveat: "An indicative estimate, not a binding appraisal.",
  };
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/portfolio")) {
      return { ok: true, status: 200, json: async () => body };
    }
    if (String(url).includes("/collection/insurance")) {
      return { ok: true, status: 200, json: async () => insurance };
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

  it("renders the responsive table with data-labels on every holding cell", async () => {
    // The responsive layout switches presentation via CSS media queries on ONE
    // DOM; jsdom has no layout engine, so we assert the enabling structure —
    // each holding cell carries a data-label that the stacked-card CSS turns
    // into its key. This is what makes the mobile layout work without a second
    // DOM tree.
    stubFetch(portfolio());

    const { container } = render(<PortfolioView onBack={() => {}} />);

    await waitFor(() => {
      expect(container.querySelector(".portfolio-table")).not.toBeNull();
    });

    const rows = container.querySelectorAll(".portfolio-table .holding-row");
    expect(rows.length).toBe(2);

    const firstRow = rows[0];
    const labelled = firstRow.querySelectorAll("td[data-label]");
    // Eight columns: Qty, Card, Variant, Set, Paid, Market, Unrealised, Actions.
    expect(labelled.length).toBe(8);
    const labels = [...labelled].map((cell) => cell.getAttribute("data-label"));
    expect(labels).toEqual(
      expect.arrayContaining(["Qty", "Card", "Variant", "Set", "Paid", "Market", "Unrealised", "Actions"]),
    );

    // The wrapper provides the overflow-x fallback guard.
    expect(container.querySelector(".portfolio-table-wrap")).not.toBeNull();
  });
  // A brand-new user's portfolio comes back with a real summary whose every
  // figure is zero. Rendering the valuation block off that asserts a $0.00
  // market value and cost basis for a collection that does not exist — a
  // fabricated valuation. Nothing to value → no valuation block, just the
  // honest empty state (the same trade Dashboard.tsx makes).
  it("shows no valuation block for an empty collection — never a fabricated $0.00", async () => {
    stubFetch(
      portfolio({
        summary: {
          market_value: 0,
          cost_basis: 0,
          unrealized: 0,
          unpriced_items: 0,
          priced_items: 0,
          allocation: [],
          top_gainers: [],
          top_losers: [],
        },
        items: [],
      }),
    );

    const { container } = render(<PortfolioView />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/nothing here yet/i);
    });
    expect(container.querySelector(".valuation")).toBeNull();
    const text = container.textContent ?? "";
    expect(text).not.toContain("$0.00");
    expect(text).not.toMatch(/market value/i);
    expect(text).not.toMatch(/cost basis/i);
  });

  // The flip side: a GENUINE zero must still be reported. Holdings that are
  // all unpriced really are worth $0.00 so far, and the caveat says why.
  // Suppressing that would be its own dishonesty.
  it("still reports a genuine $0.00 market value when real holdings are all unpriced", async () => {
    stubFetch(
      portfolio({
        summary: {
          market_value: 0,
          cost_basis: 200.0,
          unrealized: -200.0,
          unpriced_items: 1,
          priced_items: 0,
          allocation: [],
          top_gainers: [],
          top_losers: [],
        },
        items: [unpricedItem()],
      }),
    );

    const { container } = render(<PortfolioView />);

    await waitFor(() => {
      expect(container.querySelector(".valuation")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/market value/i);
    expect(text).toContain("$0.00");
    expect(text).toMatch(/count as zero — never guessed/i);
  });
});
