import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import Wants from "../components/Wants";
import type { WantItem } from "../api/types";

function slot(over: Partial<WantItem> = {}): WantItem {
  return {
    card_id: "base1-4",
    variant: "normal",
    target_price: null,
    note: null,
    added_at: "2026-08-24T00:00:00Z",
    card_name: "Charizard",
    set_id: "base1",
    set_name: "Base Set",
    number: "4",
    rarity: "Rare Holo",
    image_small: null,
    image_large: null,
    market_price: null,
    market_source: null,
    market_source_updated_at: null,
    deal_gap: null,
    within_target: null,
    ...over,
  };
}

// Fetch stub routed by URL substring + method. GET /wants -> {items};
// DELETE /wants/items/... -> 204; PATCH -> updated item.
function stubFetch(opts: {
  items?: WantItem[];
  deleteStatus?: number;
  listStatus?: number;
} = {}) {
  const items = opts.items ?? [];
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.match(/\/wants\/items\//) && method === "DELETE") {
      return { ok: (opts.deleteStatus ?? 204) < 400, status: opts.deleteStatus ?? 204, json: async () => ({}) };
    }
    if (u.match(/\/wants\/items\//) && method === "PATCH") {
      const body = JSON.parse((init?.body as string) ?? "{}");
      const idx = items.findIndex(
        (i) => u.includes(encodeURIComponent(i.card_id)) && u.includes(encodeURIComponent(i.variant)),
      );
      const patched = {
        ...items[idx],
        ...(body.target_price !== undefined ? { target_price: body.target_price } : {}),
        ...(body.note !== undefined ? { note: body.note } : {}),
      };
      // Recompute honest derived fields when both sides present.
      let deal_gap: number | null = null;
      let within_target: boolean | null = null;
      if (patched.target_price != null && patched.market_price != null) {
        deal_gap = patched.target_price - patched.market_price;
        within_target = patched.market_price <= patched.target_price;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ...patched, deal_gap, within_target }),
      };
    }
    if (u.endsWith("/wants")) {
      const ok = (opts.listStatus ?? 200) < 400;
      return { ok, status: opts.listStatus ?? 200, json: async () => ({ items: ok ? items : [] }) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Wants", () => {
  it("renders an honest empty state and never fabricates a slot", async () => {
    stubFetch({ items: [] });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/your want list is empty/i);
    });
    expect(container.querySelector(".wants-slot")).toBeNull();
  });

  it("renders slots with the card name, target, and honest 'No market price yet' when unpriced", async () => {
    stubFetch({
      items: [
        slot({
          target_price: 50.0,
          market_price: null,
        }),
      ],
    });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.querySelector(".wants-name")?.textContent).toBe("Charizard");
    });
    // Target shown; market price honest, never $0.
    expect(container.textContent ?? "").toMatch(/Target/);
    expect(container.textContent ?? "").toMatch(/No market price yet/i);
    expect(container.textContent ?? "").not.toContain("$0.00");
    // No deal gap when market is missing — honest silence, not a guess.
    expect(container.querySelector(".wants-dealgap")).toBeNull();
  });

  it("renders a market price and an under-target deal gap when both present", async () => {
    stubFetch({
      items: [
        slot({
          target_price: 50.0,
          market_price: 40.0,
          market_source: "tcgplayer",
          deal_gap: 10.0,
          within_target: true,
        }),
      ],
    });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.querySelector(".wants-market-price")).toBeTruthy();
    });
    expect(container.textContent ?? "").toMatch(/Under your target by/i);
    expect(container.querySelector(".wants-dealgap")?.classList.contains("ok")).toBe(true);
  });

  it("shows an over-target deal gap in the down tone", async () => {
    stubFetch({
      items: [
        slot({
          target_price: 50.0,
          market_price: 60.0,
          deal_gap: -10.0,
          within_target: false,
        }),
      ],
    });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/Over your target by/i);
    });
    expect(container.querySelector(".wants-dealgap")?.classList.contains("down")).toBe(true);
  });

  it("removes a slot via DELETE and updates the list", async () => {
    stubFetch({
      items: [slot({ card_id: "base1-4" }), slot({ card_id: "base2-1", card_name: "Pikachu", set_id: "base2", set_name: "Jungle", number: "1" })],
    });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.querySelectorAll(".wants-slot").length).toBe(2);
    });
    const remove = container.querySelectorAll(".wants-remove")[0] as HTMLElement;
    fireEvent.click(remove);
    await waitFor(() => {
      expect(container.querySelectorAll(".wants-slot").length).toBe(1);
    });
  });

  it("shows an honest error state on a failed load and offers retry", async () => {
    stubFetch({ listStatus: 500 });
    const { container } = render(<Wants />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/request failed: 500|couldn't load/i);
    });
    expect(container.querySelector("button.link")?.textContent).toMatch(/Try again/i);
  });
});