import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { FreshnessBand, PriceFreshness as PriceFreshnessT } from "../api/types";
import PriceFreshness from "../components/PriceFreshness";

function band(over: Partial<FreshnessBand> = {}): FreshnessBand {
  return {
    label: "fresh",
    max_age_days: 7,
    holdings: 0,
    quantity: 0,
    market_value: 0,
    share: 0,
    ...over,
  };
}

function freshness(over: Partial<PriceFreshnessT> = {}): PriceFreshnessT {
  return {
    bands: [
      band({ label: "fresh", max_age_days: 7 }),
      band({ label: "aging", max_age_days: 30 }),
      band({ label: "stale", max_age_days: 90 }),
      band({ label: "outdated", max_age_days: null }),
    ],
    priced_holdings: 0,
    unpriced_holdings: 0,
    total_holdings: 0,
    priced_value_total: 0,
    oldest_fetched_at: null,
    newest_fetched_at: null,
    caveat:
      "Price freshness is measured by when the app last refreshed each holding's price (fetched_at). Stale is a prompt to refresh, never a verdict on value. Unpriced are counted separately, never $0.",
    ...over,
  };
}

function stubFetch(body: PriceFreshnessT, status = 200) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/price-freshness")) {
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("PriceFreshness", () => {
  it("renders an honest empty state when there are no holdings (never $0)", async () => {
    stubFetch(freshness({ total_holdings: 0 }));
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.querySelector(".price-freshness")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("No holdings yet");
    // All four band rows are absent for an empty collection — nothing to band.
    expect(container.querySelectorAll(".freshness-band").length).toBe(0);
    expect(text).not.toContain("$0.00");
    // Caveat still shown verbatim.
    expect(text).toContain("prompt to refresh");
  });

  it("renders an honest all-unpriced state when holdings exist but none are priced", async () => {
    stubFetch(freshness({ total_holdings: 3, unpriced_holdings: 3 }));
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("market price yet");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("3 holdings");
    expect(text).toContain("never guessed at $0");
    // No band rows when nothing is priced.
    expect(container.querySelectorAll(".freshness-band").length).toBe(0);
  });

  it("renders all four bands in order with values + shares", async () => {
    stubFetch(
      freshness({
        bands: [
          band({ label: "fresh", max_age_days: 7, holdings: 1, quantity: 1, market_value: 10, share: 0.1 }),
          band({ label: "aging", max_age_days: 30, holdings: 1, quantity: 1, market_value: 20, share: 0.2 }),
          band({ label: "stale", max_age_days: 90, holdings: 1, quantity: 1, market_value: 30, share: 0.3 }),
          band({ label: "outdated", max_age_days: null, holdings: 1, quantity: 1, market_value: 40, share: 0.4 }),
        ],
        priced_holdings: 4,
        unpriced_holdings: 0,
        total_holdings: 4,
        priced_value_total: 100,
        oldest_fetched_at: "2026-05-01T12:00:00.000Z",
        newest_fetched_at: "2026-08-23T12:00:00.000Z",
      }),
    );
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.querySelectorAll(".freshness-band").length).toBe(4);
    });
    const labels = Array.from(container.querySelectorAll(".freshness-band")).map((el) =>
      el.className.split(" ").find((c) => c.startsWith("freshness-") && c !== "freshness-band") ?? "",
    );
    expect(labels).toEqual(["freshness-fresh", "freshness-aging", "freshness-stale", "freshness-outdated"]);
    const text = container.textContent ?? "";
    expect(text).toContain("$10.00");
    expect(text).toContain("$40.00");
    expect(text).toContain("10% of priced value");
    expect(text).toContain("40% of priced value");
    expect(text).toContain("4 priced holdings");
    expect(text).toContain("2026-05-01");
    expect(text).toContain("2026-08-23");
  });

  it("shows 'no holdings' for an empty band without fabricating a value", async () => {
    stubFetch(
      freshness({
        bands: [
          band({ label: "fresh", max_age_days: 7, holdings: 1, quantity: 1, market_value: 50, share: 1.0 }),
          band({ label: "aging", max_age_days: 30, holdings: 0, quantity: 0, market_value: 0, share: 0.0 }),
          band({ label: "stale", max_age_days: 90, holdings: 0, quantity: 0, market_value: 0, share: 0.0 }),
          band({ label: "outdated", max_age_days: null, holdings: 0, quantity: 0, market_value: 0, share: 0.0 }),
        ],
        priced_holdings: 1,
        total_holdings: 1,
        priced_value_total: 50,
      }),
    );
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.querySelectorAll(".freshness-band").length).toBe(4);
    });
    const empty = container.querySelectorAll(".freshness-band.is-empty");
    expect(empty.length).toBe(3);
    const text = container.textContent ?? "";
    // Empty bands show "no holdings", not a fabricated $0.00.
    expect(text).toContain("no holdings");
    expect(text).not.toContain("$0.00");
  });

  it("notes unpriced holdings are excluded (never $0) in the summary", async () => {
    stubFetch(
      freshness({
        bands: [
          band({ label: "fresh", max_age_days: 7, holdings: 1, quantity: 1, market_value: 50, share: 1.0 }),
          band({ label: "aging", max_age_days: 30 }),
          band({ label: "stale", max_age_days: 90 }),
          band({ label: "outdated", max_age_days: null }),
        ],
        priced_holdings: 1,
        unpriced_holdings: 2,
        total_holdings: 3,
        priced_value_total: 50,
      }),
    );
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("priced holding");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("2 unpriced (excluded from bands, never $0)");
  });

  it("surfaces an honest error state on a failed load (never a fabricated fallback)", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/price-freshness")) {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    expect(container.querySelector(".error")).not.toBeNull();
  });

  it("degrades to the empty state on a 200 with the wrong shape (defensive)", async () => {
    // A misrouted proxy could return a 200 with the portfolio shape (no `bands`).
    // The component must degrade to an honest empty state, not throw.
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/price-freshness")) {
        return { ok: true, status: 200, json: async () => ({ summary: {} }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<PriceFreshness />);
    await waitFor(() => {
      expect(container.querySelector(".price-freshness")).not.toBeNull();
    });
    // No bands rendered, no crash.
    expect(container.querySelectorAll(".freshness-band").length).toBe(0);
  });
});