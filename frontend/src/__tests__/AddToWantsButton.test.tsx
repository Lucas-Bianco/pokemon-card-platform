import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import AddToWantsButton from "../components/AddToWantsButton";

// Fetch stub for the single POST /wants/items the button makes. Returns the
// given status; the body is echoed as a WantItem when ok.
function stubFetch(status: number) {
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.endsWith("/wants/items") && method === "POST") {
      if (status >= 400) {
        return { ok: false, status, json: async () => ({}) };
      }
      const body = JSON.parse((init?.body as string) ?? "{}");
      return {
        ok: true,
        status,
        json: async () => ({
          card_id: body.card_id,
          variant: body.variant,
          target_price: body.target_price ?? null,
          note: body.note ?? null,
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
        }),
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AddToWantsButton", () => {
  it("POSTs /wants/items and shows 'On your want list' on 201", async () => {
    const spy = stubFetch(201);
    const { container } = render(<AddToWantsButton cardId="base1-4" variant="normal" />);

    const btn = container.querySelector("button") as HTMLButtonElement;
    expect(btn.textContent).toMatch(/hunt this card/i);
    fireEvent.click(btn);

    await waitFor(() => {
      const postCalls = spy.mock.calls.filter(
        ([u, init]) =>
          String(u).endsWith("/wants/items") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(postCalls.length).toBeGreaterThanOrEqual(1);
      const body = JSON.parse((postCalls[0][1] as RequestInit).body as string);
      expect(body.card_id).toBe("base1-4");
      expect(body.variant).toBe("normal");
    });
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/on your want list/i);
    });
  });

  it("shows 'Already on your want list' on 409 (honest semantic, not an opaque code)", async () => {
    stubFetch(409);
    const { container } = render(<AddToWantsButton cardId="base1-4" />);
    fireEvent.click(container.querySelector("button") as HTMLButtonElement);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/already on your want list/i);
    });
  });

  it("shows 'Card not found' on 404", async () => {
    stubFetch(404);
    const { container } = render(<AddToWantsButton cardId="nope-1" />);
    fireEvent.click(container.querySelector("button") as HTMLButtonElement);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/card not found/i);
    });
  });

  it("surfaces the verbatim error on an unexpected failure (never a fabricated fallback)", async () => {
    stubFetch(500);
    const { container } = render(<AddToWantsButton cardId="base1-4" />);
    fireEvent.click(container.querySelector("button") as HTMLButtonElement);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
  });

  it("sends variant defaulting to 'normal' when omitted", async () => {
    const spy = stubFetch(201);
    const { container } = render(<AddToWantsButton cardId="base1-4" />);
    fireEvent.click(container.querySelector("button") as HTMLButtonElement);
    await waitFor(() => {
      const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
      expect(body.variant).toBe("normal");
    });
  });

  it("uses a distinct verb-phrase that does not collide with a nav tab label", async () => {
    // Do-not-break contract: the CTA must not be named "Scan" or any nav tab.
    const { container } = render(<AddToWantsButton cardId="base1-4" />);
    const btn = container.querySelector("button") as HTMLButtonElement;
    expect(btn.textContent).toMatch(/hunt this card/i);
    expect(btn.textContent).not.toMatch(/^scan$/i);
  });
});