import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor, fireEvent, act } from "@testing-library/react";
import PriceLookup from "../components/PriceLookup";

interface CardLookupResult {
  card_id: string;
  name: string;
  set_id: string;
  set_name: string;
  number: string;
  rarity: string | null;
  image_small: string | null;
  image_large: string | null;
  market: number | null;
  source: string | null;
  source_updated_at: string | null;
}

function card(over: Partial<CardLookupResult> = {}): CardLookupResult {
  return {
    card_id: "base1-4",
    name: "Charizard",
    set_id: "base1",
    set_name: "Base Set",
    number: "4",
    rarity: "Rare Holo",
    image_small: null,
    image_large: null,
    market: 350.0,
    source: "tcgplayer",
    source_updated_at: "2026-08-20T00:00:00Z",
    ...over,
  };
}

function stubFetch(opts: { cards?: CardLookupResult[]; status?: number } = {}) {
  const body: CardLookupResult[] = opts.cards ?? [
    card(),
    card({
      card_id: "sv1-122",
      name: "Pikachu ex",
      set_id: "sv1",
      set_name: "Scarlet & Violet",
      number: "122",
      rarity: "Double Rare",
      market: 12.34,
      source: "tcgplayer",
      source_updated_at: "2026-08-21T00:00:00Z",
    }),
  ];
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/cards/lookup?")) {
      return {
        ok: (opts.status ?? 200) < 400,
        status: opts.status ?? 200,
        json: async () => body,
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  cleanup();
});

describe("PriceLookup", () => {
  it("renders results with name + price", async () => {
    stubFetch();
    const { container, getByText } = render(<PriceLookup />);

    const input = document.querySelector(
      '[aria-label="Search cards by name"]',
    ) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "Char" } });
    });

    await waitFor(() =>
      expect(container.querySelector(".price-lookup-card")).toBeTruthy(),
    );
    expect(getByText("Charizard")).toBeTruthy();
    expect(getByText("Pikachu ex")).toBeTruthy();
    // Real prices render as formatted money.
    expect(container.textContent).toMatch(/\$350\.00/);
    expect(container.textContent).toMatch(/\$12\.34/);
  });

  it("null market -> 'no market price', never $0.00", async () => {
    stubFetch({
      cards: [
        card({
          card_id: "x1-1",
          name: "Unpriced Promo",
          market: null,
          source: null,
          source_updated_at: null,
        }),
      ],
      status: 200,
    });
    const { container } = render(<PriceLookup />);

    const input = document.querySelector(
      '[aria-label="Search cards by name"]',
    ) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "Promo" } });
    });

    await waitFor(() =>
      expect(container.querySelector(".price-lookup-card")).toBeTruthy(),
    );
    expect(container.textContent).toMatch(/no market price/);
    // The em dash is used for the null price in the price slot.
    expect(container.textContent).toMatch(/—/);
    expect(container.textContent).not.toMatch(/\$0\.00/);
  });

  it("debounces — does not fetch on every keystroke", async () => {
    vi.useFakeTimers();
    const spy = stubFetch();
    render(<PriceLookup />);

    const input = document.querySelector(
      '[aria-label="Search cards by name"]',
    ) as HTMLInputElement;

    // Three rapid keystrokes within the debounce window.
    await act(async () => {
      fireEvent.change(input, { target: { value: "c" } });
    });
    await act(async () => {
      fireEvent.change(input, { target: { value: "ch" } });
    });
    await act(async () => {
      fireEvent.change(input, { target: { value: "cha" } });
    });

    // Before the 300ms debounce elapses, no fetch has fired.
    expect(spy).not.toHaveBeenCalled();

    // Advance past the debounce; exactly one fetch fires (not three). The stub
    // resolves synchronously, so act() flushes the .then() microtask.
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/cards/lookup?");
    expect(url).toContain("q=cha");
    expect(url).toContain("limit=20");
  });

  it("honest empty: no query -> the 'Type a card name...' copy", async () => {
    stubFetch();
    const { container, getByText } = render(<PriceLookup />);
    // No query typed yet -> the hint, and crucially no fetch.
    expect(getByText(/Type a card name to look up its price/i)).toBeTruthy();
    expect(container.querySelector(".price-lookup-card")).toBeNull();
  });

  it("honest empty: query with [] -> 'No cards match.'", async () => {
    stubFetch({ cards: [] });
    const { container, getByText } = render(<PriceLookup />);

    const input = document.querySelector(
      '[aria-label="Search cards by name"]',
    ) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "zzznomatch" } });
    });

    await waitFor(() =>
      expect(getByText(/No cards match/i)).toBeTruthy(),
    );
    expect(container.querySelector(".price-lookup-card")).toBeNull();
  });

  it("shows staleness (source) when present", async () => {
    stubFetch();
    const { container } = render(<PriceLookup />);

    const input = document.querySelector(
      '[aria-label="Search cards by name"]',
    ) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "Char" } });
    });

    await waitFor(() =>
      expect(container.querySelector(".price-lookup-source")).toBeTruthy(),
    );
    expect(container.textContent).toMatch(/tcgplayer/);
    expect(container.textContent).toMatch(/as of 2026-08-20/);
  });
});