import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { AcquisitionPoint, AcquisitionTimeline as AcquisitionTimelineT } from "../api/types";
import AcquisitionTimelineChart from "../components/AcquisitionTimelineChart";

function point(over: Partial<AcquisitionPoint> = {}): AcquisitionPoint {
  return {
    observed_at: "2026-01-01T12:00:00.000Z",
    cumulative_cards: 1,
    cumulative_cost_basis: 10.0,
    ...over,
  };
}

function timeline(over: Partial<AcquisitionTimelineT> = {}): AcquisitionTimelineT {
  return {
    points: [],
    total_holdings: 0,
    holdings_with_cost: 0,
    holdings_without_cost: 0,
    undated_holdings: 0,
    total_cards: 0,
    total_cost_basis: 0,
    caveat:
      "Collection growth from each holding's acquired_at. Cost line sums only holdings with a purchase price, never $0. Undated holdings excluded, never a point at time zero.",
    ...over,
  };
}

function stubFetch(body: AcquisitionTimelineT, status = 200) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/acquisition-timeline")) {
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("AcquisitionTimelineChart", () => {
  it("renders an honest empty state when there are no holdings (never a 0 point)", async () => {
    stubFetch(timeline({ total_holdings: 0 }));
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector(".acquisition-timeline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("No holdings yet");
    expect(container.querySelector("svg")).toBeNull();
    expect(text).toContain("never a point at time zero");
  });

  it("renders an honest empty state when all holdings are undated (never time zero)", async () => {
    stubFetch(timeline({ total_holdings: 2, undated_holdings: 2 }));
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("no acquired date");
    });
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent ?? "").toContain("time zero");
  });

  it("renders a single dot + an honest 'need more history' note for one point", async () => {
    stubFetch(
      timeline({
        points: [point({ cumulative_cards: 3, cumulative_cost_basis: 30.0 })],
        total_holdings: 1,
        holdings_with_cost: 1,
        total_cards: 3,
        total_cost_basis: 30.0,
      }),
    );
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector("svg circle")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("One acquisition");
    expect(text).toContain("3 cards");
    expect(text).toContain("need more history");
    // No polyline for a single point — a line would imply a trend that isn't there.
    expect(container.querySelector("svg polyline")).toBeNull();
  });

  it("renders a line chart with min/max/current cards for multiple points", async () => {
    stubFetch(
      timeline({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", cumulative_cards: 2, cumulative_cost_basis: 20.0 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", cumulative_cards: 5, cumulative_cost_basis: 20.0 }),
          point({ observed_at: "2026-03-01T12:00:00.000Z", cumulative_cards: 6, cumulative_cost_basis: 50.0 }),
        ],
        total_holdings: 3,
        holdings_with_cost: 2,
        holdings_without_cost: 1,
        total_cards: 6,
        total_cost_basis: 50.0,
      }),
    );
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("min 2");
    expect(text).toContain("max 6");
    expect(text).toContain("6 cards");
    expect(container.querySelectorAll("svg circle").length).toBe(3);
  });

  it("notes cost basis known-for-X-of-Y and never $0 when some acquisitions are unpriced", async () => {
    stubFetch(
      timeline({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", cumulative_cards: 2, cumulative_cost_basis: 20.0 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", cumulative_cards: 5, cumulative_cost_basis: 20.0 }),
        ],
        total_holdings: 2,
        holdings_with_cost: 1,
        holdings_without_cost: 1,
        total_cards: 5,
        total_cost_basis: 20.0,
      }),
    );
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("known for 1 of 2 holdings");
    expect(text).toContain("never $0");
  });

  it("notes undated holdings are excluded when present", async () => {
    stubFetch(
      timeline({
        points: [
          point({ observed_at: "2026-01-01T12:00:00.000Z", cumulative_cards: 2, cumulative_cost_basis: 20.0 }),
          point({ observed_at: "2026-02-01T12:00:00.000Z", cumulative_cards: 3, cumulative_cost_basis: 30.0 }),
        ],
        total_holdings: 3,
        holdings_with_cost: 2,
        undated_holdings: 1,
        total_cards: 4,
        total_cost_basis: 30.0,
      }),
    );
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector("svg polyline")).not.toBeNull();
    });
    expect(container.textContent ?? "").toContain("1 undated (excluded)");
  });

  it("surfaces an honest error state on a failed load (never a fabricated fallback)", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/acquisition-timeline")) {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    expect(container.querySelector(".error")).not.toBeNull();
  });

  it("degrades to the empty state on a 200 with the wrong shape (defensive)", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/acquisition-timeline")) {
        return { ok: true, status: 200, json: async () => ({ summary: {} }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<AcquisitionTimelineChart />);
    await waitFor(() => {
      expect(container.querySelector(".acquisition-timeline")).not.toBeNull();
    });
    expect(container.querySelectorAll("svg").length).toBe(0);
  });
});