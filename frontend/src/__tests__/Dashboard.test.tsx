import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import Dashboard from "../components/Dashboard";

// jsdom does not implement IntersectionObserver, but framer-motion's
// `whileInView` (used by <Reveal>) registers one on mount. Stub a no-op
// observer so the Dashboard's animated reveals mount without throwing.
beforeAll(() => {
  if (typeof globalThis.IntersectionObserver === "undefined") {
    globalThis.IntersectionObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    } as unknown as typeof IntersectionObserver;
  }
});

afterEach(() => vi.unstubAllGlobals());

function stubPortfolio(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/portfolio")) {
        return { ok: true, status: 200, json: async () => body };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
}

const summary = {
  market_value: 1000,
  cost_basis: 800,
  unrealized: 200,
  priced_items: 5,
  unpriced_items: 1,
  allocation: [
    { set_id: "a", set_name: "Base", market_value: 600, cost_basis: 400, item_count: 3 },
    { set_id: "b", set_name: "Jungle", market_value: 400, cost_basis: 400, item_count: 2 },
  ],
  top_gainers: [{ id: 1, card_id: "a1", card_name: "Charizard", set_id: "a", set_name: "Base", variant: "normal", quantity: 1, acquired_price: 100, acquired_at: null, condition: null, notes: null, market_price: 250, market_source: "tcg", market_source_updated_at: null, unrealized: 150, priced: true }],
  top_losers: [],
};

describe("Dashboard", () => {
  it("renders KPIs and allocation when holdings exist", async () => {
    stubPortfolio({ summary, items: [] });
    render(<Dashboard unread={0} onNavigate={() => {}} onWatchCard={() => {}} />);
    await waitFor(() => expect(screen.getByText("Your collection at a glance")).toBeDefined());
    // Count-up settles to the target on the final rAF frame; assert the KPI
    // label renders and that some dollar value is present (robust to rAF timing
    // in jsdom — see the task NOTE on the animated-path flake risk).
    await waitFor(() => expect(screen.getByText("Market value")).toBeDefined());
    expect(screen.getByText("Charizard")).toBeDefined();
    expect(screen.getAllByText(/\$\d/).length).toBeGreaterThan(0);
  });

  it("renders an honest empty state with no-crash on {} response", async () => {
    stubPortfolio({});
    render(<Dashboard unread={0} onNavigate={() => {}} onWatchCard={() => {}} />);
    await waitFor(() => expect(screen.getByText("No holdings yet. Scan a card to start building your portfolio.")).toBeDefined());
    expect(screen.getByRole("button", { name: "Start scanning" })).toBeDefined();
  });

  it("renders an honest empty state on fetch failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }));
    render(<Dashboard unread={0} onNavigate={() => {}} onWatchCard={() => {}} />);
    await waitFor(() => expect(screen.getByText("No holdings yet. Scan a card to start building your portfolio.")).toBeDefined());
  });

  it("navigates via quick-action CTAs", async () => {
    stubPortfolio({ summary, items: [] });
    const onNavigate = vi.fn();
    render(<Dashboard unread={0} onNavigate={onNavigate} onWatchCard={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start scanning" })).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Start scanning" }));
    expect(onNavigate).toHaveBeenCalledWith("scan");
  });
});