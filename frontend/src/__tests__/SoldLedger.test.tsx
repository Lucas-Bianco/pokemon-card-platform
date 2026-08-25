import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import SoldLedger from "../components/SoldLedger";

// A fetch router: routes by URL so the mount-time Promise.all of
// getSoldLots (GET /sold-lots) + getSoldSummary (GET /sold-lots/summary) both
// resolve, and POST/DELETE return canned responses. Captures calls so tests
// can assert the form posted the right body / hit the delete route.
function makeFetcher(opts: { lots?: any[]; summary?: any } = {}) {
  const lots = opts.lots ?? [];
  const summary = opts.summary ?? {
    lot_count: 0,
    lots_with_cost: 0,
    lots_without_cost: 0,
    total_proceeds: 0,
    total_cost_basis: 0,
    total_realized: 0,
    winners: 0,
    losers: 0,
    caveat: "honest",
  };
  const calls: { url: string; method: string; body?: string }[] = [];
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body as string | undefined });
    let json: any;
    let status = 200;
    if (url.endsWith("/sold-lots/summary")) {
      json = summary;
    } else if (url.endsWith("/sold-lots")) {
      if (method === "POST") {
        // Echo back a created lot with derived fields.
        const payload = JSON.parse(init?.body as string);
        json = {
          id: 99,
          card_id: payload.card_id,
          variant: payload.variant,
          quantity: payload.quantity,
          sale_price: payload.sale_price,
          sale_fee: payload.sale_fee,
          acquired_price: payload.acquired_price,
          sold_at: "2026-01-01T00:00:00Z",
          source: payload.source,
          notes: payload.notes,
          card_name: "Charizard",
          set_id: "base1",
          set_name: "Base",
          number: "4",
          proceeds: (payload.sale_price - (payload.sale_fee ?? 0)) * payload.quantity,
          cost_basis: payload.acquired_price != null ? payload.acquired_price * payload.quantity : null,
          realized:
            payload.acquired_price != null
              ? (payload.sale_price - (payload.sale_fee ?? 0)) * payload.quantity -
                payload.acquired_price * payload.quantity
              : null,
        };
        status = 201;
      } else {
        json = { items: lots };
      }
    } else if (/\/sold-lots\/\d+$/.test(url) && method === "DELETE") {
      json = {};
      status = 204;
    } else {
      json = {};
    }
    return { ok: status < 400, status, json: async () => json, text: async () => "" };
  });
  vi.stubGlobal("fetch", spy);
  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SoldLedger", () => {
  it("renders the heading + honest 'never $0' note", () => {
    makeFetcher();
    render(<SoldLedger />);
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/sold lots/i);
    expect(text).toMatch(/never \$0/i);
  });

  it("empty ledger shows an honest empty state and no zeroed summary block (never a fabricated $0.00)", async () => {
    makeFetcher();
    render(<SoldLedger />);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/no sales recorded yet/i);
    });
    // No sales -> no summary block of zeros, mirroring the vault's
    // valuation-behind-hasHoldings honest-empty pattern.
    expect(document.querySelector(".sold-summary")).toBeNull();
    expect(document.body.textContent ?? "").not.toContain("$0.00");
  });

  it("renders lots with realized P/L and an em dash when no cost basis (never $0)", async () => {
    makeFetcher({
      lots: [
        {
          id: 1, card_id: "base1-4", variant: "normal", quantity: 2, sale_price: 50,
          sale_fee: 5, acquired_price: 20, sold_at: "2026-01-01T00:00:00Z",
          source: "eBay", notes: null, card_name: "Charizard", set_id: "base1",
          set_name: "Base", number: "4", proceeds: 90, cost_basis: 40, realized: 50,
        },
        {
          id: 2, card_id: "base2-1", variant: "normal", quantity: 1, sale_price: 30,
          sale_fee: null, acquired_price: null, sold_at: "2026-02-01T00:00:00Z",
          source: null, notes: null, card_name: "Pikachu", set_id: "base2",
          set_name: "Jungle", number: "1", proceeds: 30, cost_basis: null, realized: null,
        },
      ],
      summary: {
        lot_count: 2, lots_with_cost: 1, lots_without_cost: 1, total_proceeds: 120,
        total_cost_basis: 40, total_realized: 50, winners: 1, losers: 0, caveat: "honest",
      },
    });
    render(<SoldLedger />);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Charizard");
    });
    const text = document.body.textContent ?? "";
    expect(text).toContain("Charizard");
    expect(text).toContain("Pikachu");
    // Realized +50 for the cost-known lot; the no-cost lot shows — (unknown, never $0).
    expect(text).toContain("+$50.00");
    // Delete button present per row.
    expect([...document.querySelectorAll("button")].filter((b) => /delete/i.test(b.textContent ?? "")).length).toBe(2);
  });

  it("opens the form on 'Log a sale' and POSTs a new sale, then reloads", async () => {
    const { calls } = makeFetcher();
    render(<SoldLedger />);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/no sales recorded yet/i);
    });
    const toggle = [...document.querySelectorAll("button")].find((b) =>
      /log a sale/i.test(b.textContent ?? ""),
    )!;
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(document.querySelector("form.sold-form")).not.toBeNull();
    });
    // Fill required fields.
    const inputs = document.querySelectorAll("input");
    const cardInput = [...inputs].find((i) => i.getAttribute("aria-label") === "Card id")!;
    const priceInput = [...inputs].find((i) => i.getAttribute("aria-label") === "Sale price")!;
    fireEvent.change(cardInput, { target: { value: "base1-4" } });
    fireEvent.change(priceInput, { target: { value: "50" } });
    const submit = [...document.querySelectorAll("button")].find((b) =>
      /save sale/i.test(b.textContent ?? ""),
    )!;
    fireEvent.click(submit);
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/sold-lots"))).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST")!;
    const body = JSON.parse(post.body!);
    expect(body.card_id).toBe("base1-4");
    expect(body.sale_price).toBe(50);
  });

  it("prefill populates card id / variant / cost basis and opens the form", async () => {
    makeFetcher();
    const { rerender } = render(<SoldLedger />);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/no sales recorded yet/i);
    });
    rerender(
      <SoldLedger
        prefill={{
          card_id: "base1-4",
          variant: "reverseHolofoil",
          card_name: "Charizard",
          acquired_price: 20,
        }}
      />,
    );
    await waitFor(() => {
      expect(document.querySelector("form.sold-form")).not.toBeNull();
    });
    const cardInput = [...document.querySelectorAll("input")].find(
      (i) => i.getAttribute("aria-label") === "Card id",
    )! as HTMLInputElement;
    const variantInput = [...document.querySelectorAll("input")].find(
      (i) => i.getAttribute("aria-label") === "Variant",
    )! as HTMLInputElement;
    const costInput = [...document.querySelectorAll("input")].find(
      (i) => i.getAttribute("aria-label") === "Cost basis per unit",
    )! as HTMLInputElement;
    expect(cardInput.value).toBe("base1-4");
    expect(variantInput.value).toBe("reverseHolofoil");
    expect(costInput.value).toBe("20");
  });

  it("rejects an empty sale price with an honest form error (no POST)", async () => {
    const { calls } = makeFetcher();
    render(<SoldLedger />);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/no sales recorded yet/i);
    });
    fireEvent.click(
      [...document.querySelectorAll("button")].find((b) => /log a sale/i.test(b.textContent ?? ""))!,
    );
    await waitFor(() => expect(document.querySelector("form.sold-form")).not.toBeNull());
    const cardInput = [...document.querySelectorAll("input")].find(
      (i) => i.getAttribute("aria-label") === "Card id",
    )!;
    fireEvent.change(cardInput, { target: { value: "base1-4" } });
    fireEvent.click(
      [...document.querySelectorAll("button")].find((b) => /save sale/i.test(b.textContent ?? ""))!,
    );
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/enter a sale price/i);
    });
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("deletes a lot on Delete click", async () => {
    const { calls } = makeFetcher({
      lots: [
        {
          id: 7, card_id: "base1-4", variant: "normal", quantity: 1, sale_price: 10,
          sale_fee: null, acquired_price: null, sold_at: "2026-01-01T00:00:00Z",
          source: null, notes: null, card_name: "Charizard", set_id: "base1",
          set_name: "Base", number: "4", proceeds: 10, cost_basis: null, realized: null,
        },
      ],
      summary: {
        lot_count: 1, lots_with_cost: 0, lots_without_cost: 1, total_proceeds: 10,
        total_cost_basis: 0, total_realized: 0, winners: 0, losers: 0, caveat: "honest",
      },
    });
    render(<SoldLedger />);
    await waitFor(() => expect(document.body.textContent ?? "").toContain("Charizard"));
    fireEvent.click(
      [...document.querySelectorAll("button")].find((b) => /delete/i.test(b.textContent ?? ""))!,
    );
    await waitFor(() => {
      expect(calls.some((c) => c.method === "DELETE" && /\/sold-lots\/7$/.test(c.url))).toBe(true);
    });
  });
});