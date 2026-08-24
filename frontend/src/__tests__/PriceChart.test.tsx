import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PricePoint } from "../api/types";
import PriceChart from "../components/PriceChart";

function point(overrides: Partial<PricePoint> = {}): PricePoint {
  return {
    fetched_at: "2026-07-29T12:00:00Z",
    source: "tcgplayer",
    variant: "holofoil",
    market: 100.0,
    source_updated_at: "2026/07/29",
    ...overrides,
  };
}

describe("PriceChart", () => {
  it("renders 'No price history yet' when points is empty", () => {
    const { container } = render(<PriceChart points={[]} variant="holofoil" />);

    expect(container.textContent ?? "").toMatch(/no price history yet/i);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders a single dot and a 'need more history' note for one point", () => {
    const { container } = render(<PriceChart points={[point()]} variant="holofoil" />);

    expect(container.querySelector("circle")).not.toBeNull();
    expect(container.textContent ?? "").toMatch(/need more history/i);
  });

  it("renders a polyline and min/max/current labels for multiple points", () => {
    const points = [
      point({ market: 80.0, source_updated_at: "2026/07/01", fetched_at: "2026-07-01T12:00:00Z" }),
      point({ market: 100.0, source_updated_at: "2026/07/15", fetched_at: "2026-07-15T12:00:00Z" }),
      point({ market: 90.0, source_updated_at: "2026/07/29", fetched_at: "2026-07-29T12:00:00Z" }),
    ];

    const { container } = render(<PriceChart points={points} variant="holofoil" />);

    expect(container.querySelector("polyline")).not.toBeNull();
    const text = container.textContent ?? "";
    expect(text).toContain("min");
    expect(text).toContain("max");
    expect(text).toContain("current");
  });

  it("surfaces the source and source_updated_at of the latest point", () => {
    // A price is never presented without saying where it came from — the chart caption
    // carries the latest point's source and its source_updated_at, like every price wire.
    const points = [
      point({
        market: 80.0,
        source: "cardmarket",
        source_updated_at: "2026/07/01",
        fetched_at: "2026-07-01T12:00:00Z",
      }),
      point({
        market: 100.0,
        source: "tcgplayer",
        source_updated_at: "2026/07/29",
        fetched_at: "2026-07-29T12:00:00Z",
      }),
    ];

    const { container } = render(<PriceChart points={points} variant="holofoil" />);

    const text = container.textContent ?? "";
    expect(text).toContain("tcgplayer");
    expect(text).toContain("2026/07/29");
  });

  it("renders an 'unpriced' note rather than a flat zero line when all market values are null", () => {
    const points = [point({ market: null }), point({ market: null })];

    const { container } = render(<PriceChart points={points} variant="holofoil" />);

    expect(container.textContent ?? "").toMatch(/unpriced/i);
    expect(container.querySelector("polyline")).toBeNull();
  });

  it("states the point count and the append-only depth caveat for a multi-point trend", () => {
    // A short line is a young history, not censored data. The caption makes the
    // number of points legible and says snapshots are append-only, so a shallow
    // trend is never read as a full market lifetime.
    const points = [
      point({ market: 80.0, source_updated_at: "2026/07/01", fetched_at: "2026-07-01T12:00:00Z" }),
      point({ market: 100.0, source_updated_at: "2026/07/15", fetched_at: "2026-07-15T12:00:00Z" }),
      point({ market: 90.0, source_updated_at: "2026/07/29", fetched_at: "2026-07-29T12:00:00Z" }),
    ];

    const { container } = render(<PriceChart points={points} variant="holofoil" />);

    const depth = container.querySelector(".chart-depth");
    expect(depth).not.toBeNull();
    const text = depth?.textContent ?? "";
    expect(text).toContain("3 points");
    expect(text).toMatch(/depth depends on price-refresh cadence/i);
    expect(text).toMatch(/append-only/i);
    expect(text).toMatch(/never trimmed/i);
  });
});