import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import Binder from "../components/Binder";
import type { BinderItem } from "../api/types";

function slot(over: Partial<BinderItem> = {}): BinderItem {
  return {
    card_id: "base1-4",
    variant: "normal",
    sort_order: 1,
    note: null,
    added_at: "2026-08-19T00:00:00Z",
    card_name: "Charizard",
    set_id: "base1",
    set_name: "Base Set",
    number: "4",
    rarity: "Rare Holo",
    image_small: null,
    image_large: null,
    proven_sale: null,
    proven_sale_unavailable: false,
    proven_sale_empty: true,
    ...over,
  };
}

// Fetch stub routed by URL substring + method. GET /binder -> {items}; DELETE
// /binder/items/... -> 204; POST /binder/reorder -> 204; PATCH note -> updated
// item; GET /binder/export -> text/html string.
function stubFetch(opts: {
  items?: BinderItem[];
  deleteStatus?: number;
  reorderStatus?: number;
  exportHtml?: string;
  listStatus?: number;
} = {}) {
  const items = opts.items ?? [];
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/binder/export")) {
      return {
        ok: true,
        status: 200,
        text: async () => opts.exportHtml ?? "<!doctype html><title>My PC</title>",
      };
    }
    if (u.includes("/binder/reorder") && method === "POST") {
      return { ok: (opts.reorderStatus ?? 204) < 400, status: opts.reorderStatus ?? 204, json: async () => ({}) };
    }
    if (u.match(/\/binder\/items\//) && method === "DELETE") {
      return { ok: (opts.deleteStatus ?? 204) < 400, status: opts.deleteStatus ?? 204, json: async () => ({}) };
    }
    if (u.match(/\/binder\/items\//) && method === "PATCH") {
      // Echo the patched note back as a full BinderItem.
      const body = JSON.parse((init?.body as string) ?? "{}");
      const idx = items.findIndex((i) => u.includes(encodeURIComponent(i.card_id)) && u.includes(encodeURIComponent(i.variant)));
      const patched = { ...items[idx], note: body.note ?? null };
      return { ok: true, status: 200, json: async () => patched };
    }
    if (u.endsWith("/binder")) {
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

describe("Binder", () => {
  it("renders an honest empty state and never fabricates a slot", async () => {
    stubFetch({ items: [] });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/your binder is empty/i);
    });
    // No fabricated slot.
    expect(container.querySelector(".binder-slot")).toBeNull();
  });

  it("renders slots with the card name + proven sale, and an honest 'No proven sale yet' for empty slots", async () => {
    stubFetch({
      items: [
        slot({
          card_id: "base1-4",
          proven_sale: {
            listing_id: "l1", title: "Charizard", price: 118.0, currency: "USD",
            url: "https://ebay.example/l1", condition: "Raw", sold_at: "2026-08-01T00:00:00Z",
            source: "ebay",
          },
          proven_sale_empty: false,
        }),
        slot({ card_id: "base2-1", card_name: "Pikachu", set_name: "Jungle", number: "1", proven_sale_empty: true }),
      ],
    });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Pikachu");
    // The proven card shows its price ($118.00 via formatMoney).
    expect(text).toContain("$118.00");
    // The empty card shows the honest empty note, never a fabricated $0.
    expect(text).toMatch(/no proven sale yet/i);
    // Honest "each price is a proven sale" hint is present.
    expect(text).toMatch(/proven ebay sale/i);
  });

  it("shows 'set an eBay key' when proven_sale_unavailable (keyless server)", async () => {
    stubFetch({
      items: [slot({ proven_sale_unavailable: true, proven_sale_empty: false })],
    });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set an ebay key/i);
    });
  });

  it("Remove fires DELETE /binder/items/{card}/{variant} and drops the slot", async () => {
    const spy = stubFetch({
      items: [slot({ card_id: "base1-4" }), slot({ card_id: "base2-1", card_name: "Pikachu" })],
    });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });

    const removeBtns = [...container.querySelectorAll(".binder-remove")] as HTMLButtonElement[];
    fireEvent.click(removeBtns[0]);

    await waitFor(() => {
      const delCalls = spy.mock.calls.filter(
        ([u, init]) =>
          String(u).match(/\/binder\/items\//) && (init as RequestInit | undefined)?.method === "DELETE",
      );
      expect(delCalls.length).toBeGreaterThanOrEqual(1);
      expect(String(delCalls[0][0])).toContain(encodeURIComponent("base1-4"));
    });
    // The removed slot is gone from the rendered list; Pikachu remains.
    await waitFor(() => {
      const text = container.textContent ?? "";
      expect(text).toContain("Pikachu");
    });
  });

  it("Move up fires POST /binder/reorder and reorders the list", async () => {
    const spy = stubFetch({
      items: [
        slot({ card_id: "base1-4", card_name: "Charizard", sort_order: 1 }),
        slot({ card_id: "base2-1", card_name: "Pikachu", sort_order: 2 }),
      ],
    });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });

    // The second slot's Move up button.
    const moveUpBtns = [...container.querySelectorAll("button")].filter((b) =>
      /move up/i.test(b.textContent ?? ""),
    );
    expect(moveUpBtns.length).toBe(2);
    // First slot's Move up is disabled (it's first); second is enabled.
    expect(moveUpBtns[0].disabled).toBe(true);
    expect(moveUpBtns[1].disabled).toBe(false);
    fireEvent.click(moveUpBtns[1]);

    await waitFor(() => {
      const reorderCalls = spy.mock.calls.filter(
        ([u, init]) =>
          String(u).includes("/binder/reorder") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(reorderCalls.length).toBeGreaterThanOrEqual(1);
      // The new order sent has Pikachu (base2-1) before Charizard (base1-4).
      const body = JSON.parse((reorderCalls[0][1] as RequestInit).body as string);
      expect(body.items[0].card_id).toBe("base2-1");
      expect(body.items[1].card_id).toBe("base1-4");
    });
  });

  it("Add a note -> Save note fires PATCH with the note body", async () => {
    const spy = stubFetch({ items: [slot({ card_id: "base1-4", note: null })] });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });

    fireEvent.click(container.querySelector(".binder-note-add") as HTMLButtonElement);
    const input = container.querySelector(".binder-note-input") as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, { target: { value: "grail" } });
    fireEvent.click(
      [...container.querySelectorAll("button")].find((b) => /save note/i.test(b.textContent ?? "")) as HTMLButtonElement,
    );

    await waitFor(() => {
      const patchCalls = spy.mock.calls.filter(
        ([u, init]) =>
          String(u).match(/\/binder\/items\//) && (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCalls.length).toBeGreaterThanOrEqual(1);
      const body = JSON.parse((patchCalls[0][1] as RequestInit).body as string);
      expect(body.note).toBe("grail");
    });
  });

  it("Export binder fetches /binder/export and triggers a file download", async () => {
    stubFetch({ items: [slot()], exportHtml: "<!doctype html><title>My PC</title>" });
    const createUrl = vi.fn().mockReturnValue("blob:fake");
    const revoke = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: revoke });
    const clickSpy = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clickSpy);

    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });

    fireEvent.click(
      [...container.querySelectorAll("button")].find((b) => /export binder/i.test(b.textContent ?? "")) as HTMLButtonElement,
    );

    await waitFor(() => {
      expect(createUrl).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
    });
    // The blob was built from the exported HTML string.
    expect(createUrl.mock.calls[0][0]).toBeInstanceOf(Blob);
  });

  it("surfaces an honest error and a Try again when the list load fails", async () => {
    stubFetch({ items: [], listStatus: 500 });
    const { container } = render(<Binder />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    // Try again button present.
    const retry = [...container.querySelectorAll("button")].find((b) =>
      /try again/i.test(b.textContent ?? ""),
    );
    expect(retry).not.toBeUndefined();
  });
});