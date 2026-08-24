import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { Price } from "../api/types";
import PriceLine from "../components/PriceLine";

// A realistic TCGplayer-via-pokemontcg.io snapshot: a market figure sitting
// inside a low/mid/high band. Every figure travels with its source.
function price(over: Partial<Price> = {}): Price {
  return {
    source: "tcgplayer",
    variant: "holofoil",
    low: 90.0,
    mid: 100.0,
    high: 120.0,
    market: 100.0,
    source_updated_at: "2026/07/29",
    ...over,
  };
}

// PriceLine first tries the cached resolved price (GET /cards/{id}/price); if
// that resolves it never refreshes. So stubbing the GET is enough.
function stubResolvedPrice(body: Price | null) {
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (path.includes("/cards/") && path.includes("/price") && (!init || init.method === undefined)) {
      return body === null
        ? { ok: false, status: 404, json: async () => ({}) }
        : { ok: true, status: 200, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("PriceLine", () => {
  it("renders the compact line (market + raw source) by default", async () => {
    stubResolvedPrice(price());
    const { container } = render(<PriceLine cardId="base1-4" variant="holofoil" initial={null} />);
    await waitFor(() => {
      expect(container.querySelector(".price")).not.toBeNull();
    });
    expect(container.querySelector(".price-band")).toBeNull();
    const text = container.textContent ?? "";
    expect(text).toContain("$100.00");
    // The compact line shows the raw source slug, not the friendly label.
    expect(text).toContain("tcgplayer");
    expect(text).not.toMatch(/TCGplayer market reference/i);
  });

  it("renders the low/mid/high band and a legible source label when showBand is true", async () => {
    stubResolvedPrice(price());
    const { container } = render(
      <PriceLine cardId="base1-4" variant="holofoil" initial={null} showBand />,
    );
    await waitFor(() => {
      expect(container.querySelector(".price-band")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    // The band surfaces all three figures, not just the market point.
    expect(text).toContain("$90.00"); // low
    expect(text).toContain("$100.00"); // mid / market
    expect(text).toContain("$120.00"); // high
    expect(text).toMatch(/low/i);
    expect(text).toMatch(/high/i);
    // The opaque slug is translated to a legible "market reference" label.
    expect(text).toMatch(/TCGplayer market reference/i);
    expect(text).not.toContain("tcgplayer");
  });

  it("labels the cardmarket fallback as 'Cardmarket aggregate'", async () => {
    stubResolvedPrice(price({ source: "cardmarket" }));
    const { container } = render(
      <PriceLine cardId="base1-4" variant="holofoil" initial={null} showBand />,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/Cardmarket aggregate/i);
    });
  });

  it("shows 'No price available' honestly when nothing resolves", async () => {
    stubResolvedPrice(null);
    const { container } = render(
      <PriceLine cardId="base1-4" variant="holofoil" initial={null} showBand />,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no price available/i);
    });
    // Never a fabricated band of zeros.
    expect(container.querySelector(".price-band")).toBeNull();
    expect(container.textContent ?? "").not.toContain("$0.00");
  });
});