import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { PortfolioHistory, PortfolioValuePoint } from "../api/types";
import PortfolioHistoryChart from "../components/PortfolioHistoryChart";

function point(over: Partial<PortfolioValuePoint> = {}): PortfolioValuePoint {
  return {
    observed_at: "2026-01-01T12:00:00.000Z",
    market_value: 100.0,
    priced_items: 2,
    unpriced_items: 0,
    ...over,
  };
}

function history(over: Partial<PortfolioHistory> = {}): PortfolioHistory {
  return {
    points: [],
    priced_items: 0,
    unpriced_items: 0,
    total_items: 0,
    caveat: "Reconstructed from append-only snapshots. Current holdings, never $0. Cadence caveat.",
    ...over,
  };
}

function stubFetch(body: PortfolioHistory, status = 200) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/portfolio/history")) {
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("PortfolioHistoryChart", () => {
  it("renders an honest empty state when there are no holdings (never a $0 line)", async () => {
    stubFetch(history({ total_items: 0 }));
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.querySelector(".portfolio-history")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("No holdings yet");
    // No chart drawn for an empty collection.
    expect(container.querySelector("svg")).toBeNull();
    // Caveat still shown.
    expect(text).toContain("Current holdings");
  });

  it("renders an honest empty state when holdings exist but have no snapshots (never $0)", async () => {
    stubFetch(history({ total_items: 3, unpriced_items: 3 }));
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("No price history yet");
    });
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("renders a single dot + an honest 'need more history' note for one point", async () => {
    stubFetch(
      history({
        points: [point({ market_value: 250.0, priced_items: 2, unpriced_items: 1 })],
        total_items: 3,
        priced_items: 2,
        unpriced_items: 1,
      }),
    );
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.querySelector("svg circle")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("One observation");
    expect(text).toContain("$250.00");
    expect(text).toContain("need more history");
    // No polyline for a single point — a line would imply a trend that isn't there.
    expect(container.querySelector("svg polyline")).toBeNull();
  });

  it("renders a line chart with min/max/current labels for multiple points", async () => {
    stubFetch(
      history({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", market_value: 100.0 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", market_value: 150.0 }),
          point({ observed_at: "2026-03-01T12:00:00.000Z", market_value: 120.0, priced_items: 2, unpriced_items: 1 }),
        ],
        total_items: 3,
        priced_items: 2,
        unpriced_items: 1,
      }),
    );
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("min");
    expect(text).toContain("$100.00");
    expect(text).toContain("max");
    expect(text).toContain("$150.00");
    expect(text).toContain("current");
    expect(text).toContain("$120.00");
    // 3 points / 3 chart dots.
    expect(container.querySelectorAll("svg circle").length).toBe(3);
  });

  it("states the depth + cadence caveat honestly, never censoring a short line", async () => {
    stubFetch(
      history({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", market_value: 100.0 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", market_value: 150.0 }),
        ],
      }),
    );
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("2 points");
    expect(text).toContain("depth depends on price-refresh cadence");
    expect(text).toContain("append-only");
  });

  it("surfaces an honest error state on a failed load (never a fabricated fallback)", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/portfolio/history")) {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    // The error class is used, not the empty-state copy.
    expect(container.querySelector(".error")).not.toBeNull();
  });

  it("notes unpriced holdings are excluded (never $0) in the caption when present", async () => {
    stubFetch(
      history({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", market_value: 100.0, priced_items: 2, unpriced_items: 1 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", market_value: 150.0, priced_items: 2, unpriced_items: 1 }),
        ],
      }),
    );
    const { container } = render(<PortfolioHistoryChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("1 unpriced (excluded, never $0)");
  });
});