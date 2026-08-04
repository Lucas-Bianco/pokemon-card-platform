import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import CardDetail from "../components/CardDetail";

const noop = () => {};

// A card body returned by GET /cards/{id} (CardOut / CardSearchResult shape).
const card = {
  id: "base1-4",
  name: "Charizard",
  number: "4",
  set_id: "base1",
  set_name: "Base",
  image_small: "https://example.com/small.png",
  image_large: "https://example.com/large.png",
};

// A grading-upside spread body returned by /grading-upside.
const upside = {
  card_id: "base1-4",
  variant: "normal",
  raw_price: { market: 120.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
  psa9: { market: 350.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
  psa10: { market: 1200.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
  grading_fee: 25.0,
  upside_to_10: 1055.0,
  graded_prices_unavailable: false,
};

const priceHistory = {
  card_id: "base1-4",
  variant: "normal",
  points: [
    { fetched_at: "2026-07-28T12:00:00Z", source: "tcgplayer", variant: "normal", market: 100.0, source_updated_at: "2026/07/28" },
    { fetched_at: "2026-07-29T12:00:00Z", source: "tcgplayer", variant: "normal", market: 120.0, source_updated_at: "2026/07/29" },
  ],
};

// Routed fetch stub: returns the matching body by URL substring so CardDetail's
// parallel fetches (card, price, grading-upside, prices/history, listings) all
// resolve. Mirrors the ScanResult/GradingUpside test stubs.
function stubFetch(options: {
  card?: typeof card | null;
  upside?: typeof upside | null;
  history?: typeof priceHistory | null;
  price?: { market: number | null; source: string; source_updated_at: string } | null;
  priceStatus?: number;
  listings?: Array<Record<string, unknown>>;
  listingsUnavailable?: boolean;
  deals?: Array<Record<string, unknown>>;
  soldComps?: Record<string, unknown>;
}) {
  const opts = {
    card,
    upside,
    history: priceHistory,
    price: { market: 800.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
    listings: [],
    listingsUnavailable: false,
    deals: [] as Array<Record<string, unknown>>,
    ...options,
  };
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.match(/\/cards\/[^/]+\/deals/)) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "normal",
          listings_unavailable: false,
          listings_empty: false,
          deals: opts.deals,
          thresholds: { deal_rip_min_abs: 2.0, deal_rip_min_pct: 0.1, deal_flip_min_abs: 20.0 },
        }),
      };
    }
    if (u.match(/\/cards\/[^/]+\/sold-comps/)) {
      return {
        ok: true,
        status: 200,
        json: async () => opts.soldComps ?? {
          card_id: "base1-4", variant: "normal",
          sold_comps: [], sold_comps_unavailable: false, sold_comps_empty: true,
        },
      };
    }
    if (u.match(/\/cards\/[^/]+\/listings/)) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ listings: opts.listings, listings_unavailable: opts.listingsUnavailable }),
      };
    }
    if (u.includes("/grading-upside")) {
      if (opts.upside === null) return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => opts.upside };
    }
    if (u.includes("/prices/history")) {
      if (opts.history === null) return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => opts.history };
    }
    // Resolved single price. 204 → no price (the honest unpriced path).
    if (u.match(/\/cards\/[^/]+\/price$/)) {
      const status = opts.priceStatus ?? 200;
      if (status === 204) return { ok: true, status: 204, json: async () => null };
      if (opts.price === null) return { ok: true, status: 204, json: async () => null };
      return { ok: true, status, json: async () => opts.price };
    }
    // Refresh price (POST) — fall through to the same body.
    if (u.match(/\/cards\/[^/]+\/prices\/refresh/)) {
      if (opts.price === null) return { ok: true, status: 204, json: async () => null };
      return { ok: true, status: 200, json: async () => opts.price };
    }
    // GET /cards/{id} — the card itself. A null card simulates a fetch failure.
    if (u.match(/\/cards\/[^/]+$/) && !u.includes("?")) {
      if (opts.card === null) return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => opts.card };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("CardDetail", () => {
  it("renders the card name, set, and number once loaded", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Base");
    expect(text).toContain("#4");
  });

  it("renders the market price with its source and staleness", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$800.00");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("tcgplayer");
    expect(text).toContain("as of 2026/07/29");
  });

  it("renders an em dash and 'no market price' when the card is unpriced (204), never $0.00", async () => {
    stubFetch({ price: null });
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no market price|no price available/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("renders the reused GradingUpside panel when the spread is present", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    // Wait for the LOADED panel, not the loading skeleton: the loading state
    // also renders a <p class="grading-upside"> ("Checking grading spread…"),
    // so querying the class alone races the fetch. The headline only renders
    // once the spread data is in.
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/spread, not a prediction/i);
    });
    expect(container.querySelector(".grading-upside")).not.toBeNull();
  });

  it("renders the reused PriceChart when history points are present", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.querySelector(".price-chart")).not.toBeNull();
    });
  });

  it("renders active listings when present", async () => {
    const listings = [
      {
        listing_id: "a1",
        title: "Charizard PSA 10",
        price: 1200.0,
        currency: "USD",
        listing_type: "fixed",
        auction_end_at: null,
        url: "https://ebay.example/x",
        condition: "PSA 10",
        source: "ebay",
        fetched_at: "2026-07-30T00:00:00Z",
      },
    ];
    stubFetch({ listings });

    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.querySelector(".listing-row")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Charizard PSA 10");
    expect(text).toContain("$1200.00");
    expect(text).toContain("ebay");
  });

  it("empty listings + unavailable → 'Set a listings source key' hint", async () => {
    stubFetch({ listings: [], listingsUnavailable: true });

    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set a listings source key/i);
    });
    expect(container.querySelector(".listing-row")).toBeNull();
  });

  it("empty listings + available → 'No active listings right now.'", async () => {
    stubFetch({ listings: [], listingsUnavailable: false });

    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no active listings right now/i);
    });
    expect(container.querySelector(".listing-row")).toBeNull();
  });

  it("shows a 'Watch this card' button (disabled/no-op in T6)", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      const btn = [...container.querySelectorAll("button")].find((b) =>
        /watch this card/i.test(b.textContent ?? ""),
      );
      expect(btn).toBeDefined();
    });
  });

  it("renders 'Couldn't load this card.' + a retry when the card fetch fails", async () => {
    // Card fetch returns 500; the component shows the honest error + retry.
    stubFetch({ card: null });

    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/couldn't load this card/i);
    });
    const retry = [...container.querySelectorAll("button")].find((b) =>
      /retry/i.test(b.textContent ?? ""),
    );
    expect(retry).toBeDefined();
  });

  it("renders a back button that calls onBack", async () => {
    stubFetch({});
    const onBack = vi.fn();
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={onBack} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard");
    });
    const back = [...container.querySelectorAll("button")].find((b) =>
      /back/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(back).toBeDefined();
    fireEvent.click(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders a RIP deal chip on a listing the deals API flagged as a rip", async () => {
    const listings = [
      {
        listing_id: "a1",
        title: "Charizard PSA 10",
        price: 1200.0,
        currency: "USD",
        listing_type: "fixed",
        auction_end_at: null,
        url: "https://ebay.example/x",
        condition: "PSA 10",
        source: "ebay",
        fetched_at: "2026-07-30T00:00:00Z",
      },
    ];
    const deals = [
      {
        listing_id: "a1",
        title: "Charizard PSA 10",
        listing_price: 1200.0,
        currency: "USD",
        url: "https://ebay.example/x",
        condition: "PSA 10",
        listing_type: "fixed_price",
        auction_end_at: null,
        fetched_at: "2026-07-30T00:00:00Z",
        raw_market: { price: 1500.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
        rip_edge: 300.0,
        psa9_comp: null,
        psa10_comp: null,
        flip_edge_to_9: null,
        flip_edge_to_10: null,
        grading_fee: 25.0,
        deal_score: 90.0,
        is_rip: true,
        is_flip: false,
      },
    ];
    stubFetch({ listings, deals });

    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.querySelector(".deal-chip.rip")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/RIP/);
    // The rip edge renders with formatMoney's no-comma convention.
    expect(text).toContain("$300.00");
  });

  it("renders the Recent sold (eBay) evidence block", async () => {
    stubFetch({
      soldComps: {
        card_id: "base1-4", variant: "normal",
        sold_comps: [{ listing_id: "a", title: "Charizard #4", price: 118.0, currency: "USD",
          url: "https://ebay.example/a", condition: "Used", sold_at: "2026-07-30T18:30:00Z", source: "ebay" }],
        sold_comps_unavailable: false, sold_comps_empty: false,
      },
    });
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$118.00");
    });
    expect(container.textContent ?? "").toMatch(/recent sold/i);
  });
});