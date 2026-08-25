import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { Diversification as DiversificationT } from "../api/types";
import DiversificationPanel from "../components/Diversification";

function diversification(over: Partial<DiversificationT> = {}): DiversificationT {
  return {
    priced_total: 100.0,
    priced_items: 3,
    unpriced_items: 1,
    total_items: 4,
    top_holdings: [
      {
        card_id: "base1-4", card_name: "Charizard", set_name: "Base", variant: "normal",
        quantity: 1, market_value: 70.0, share: 0.7, cumulative_share: 0.7,
      },
      {
        card_id: "base1-58", card_name: "Pikachu", set_name: "Base", variant: "normal",
        quantity: 1, market_value: 20.0, share: 0.2, cumulative_share: 0.9,
      },
      {
        card_id: "base2-1", card_name: "Energy", set_name: "Jungle", variant: "normal",
        quantity: 1, market_value: 10.0, share: 0.1, cumulative_share: 1.0,
      },
    ],
    concentration: { top_share: 0.7, cards_for_50: 1, cards_for_80: 2, cards_for_90: 2, priced_holdings: 3 },
    by_rarity: [
      { label: "Rare Holo", market_value: 70.0, share: 0.7, holdings: 1, quantity: 1 },
      { label: "Common", market_value: 30.0, share: 0.3, holdings: 2, quantity: 2 },
    ],
    by_supertype: [
      { label: "Pokemon", market_value: 90.0, share: 0.9, holdings: 2, quantity: 2 },
      { label: "Energy", market_value: 10.0, share: 0.1, holdings: 1, quantity: 1 },
    ],
    by_set: [
      { label: "Base", market_value: 90.0, share: 0.9, holdings: 2, quantity: 2 },
      { label: "Jungle", market_value: 10.0, share: 0.1, holdings: 1, quantity: 1 },
    ],
    caveat: "Concentration is a risk flag, not a verdict.",
    ...over,
  };
}

function stubFetch(body: DiversificationT) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/diversification")) {
      return { ok: true, status: 200, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("Diversification", () => {
  it("renders the concentration headline + tiles + top holdings", async () => {
    stubFetch(diversification());
    const { container } = render(<DiversificationPanel />);
    await waitFor(() => {
      expect(container.querySelector(".diversification")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    // Headline: top 2 carry 80% (cards_for_80).
    expect(text).toContain("top 2 cards carry 80%");
    // Largest-holding tile = 70%.
    expect(text).toContain("70%");
    // Top holdings list shows the three cards with their values + shares.
    expect(text).toContain("Charizard");
    expect(text).toContain("$70.00");
    expect(text).toContain("Pikachu");
    expect(text).toContain("Energy");
  });

  it("renders by-rarity / by-supertype / by-set breakdowns with shares", async () => {
    stubFetch(diversification());
    const { container } = render(<DiversificationPanel />);
    await waitFor(() => {
      expect(container.querySelector(".diversification")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/by rarity/i);
    expect(text).toContain("Rare Holo");
    expect(text).toMatch(/by supertype/i);
    expect(text).toContain("Pokemon");
    expect(text).toMatch(/by set/i);
    expect(text).toContain("Jungle");
  });

  it("notes unpriced cards are excluded from shares, never $0", async () => {
    stubFetch(diversification());
    const { container } = render(<DiversificationPanel />);
    await waitFor(() => {
      expect(container.querySelector(".diversification")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("1 unpriced (excluded from shares, never $0)");
  });

  it("honest all-unpriced state: no headline, no $0, honest empty note", async () => {
    stubFetch(
      diversification({
        priced_total: 0.0,
        priced_items: 0,
        unpriced_items: 2,
        total_items: 2,
        top_holdings: [],
        concentration: { top_share: null, cards_for_50: null, cards_for_80: null, cards_for_90: null, priced_holdings: 0 },
        by_rarity: [{ label: "Common", market_value: 0.0, share: 0.0, holdings: 2, quantity: 2 }],
        by_supertype: [{ label: "Pokemon", market_value: 0.0, share: 0.0, holdings: 2, quantity: 2 }],
        by_set: [{ label: "Base", market_value: 0.0, share: 0.0, holdings: 2, quantity: 2 }],
      }),
    );
    const { container } = render(<DiversificationPanel />);
    await waitFor(() => {
      expect(container.querySelector(".diversification")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    // No concentration headline (nothing priced to concentrate).
    expect(text).not.toMatch(/carry.*of your collection/);
    // Honest all-unpriced note, never a fabricated $0.
    expect(text).toMatch(/market price yet/i);
    expect(text).toMatch(/never guessed at \$0/i);
    // The all-unpriced bucket still appears at 0%.
    expect(text).toContain("Common");
  });

  it("surfaces an honest error and never a friendly fallback", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/collection/diversification")) {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<DiversificationPanel />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
  });
});