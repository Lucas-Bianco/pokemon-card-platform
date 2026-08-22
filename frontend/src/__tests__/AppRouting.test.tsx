import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "../App";
import { ToastProvider } from "../components/Toast";

// URL routing through the real <App/>. Same stub pattern as BulkScan.test.tsx:
// route global.fetch by URL substring and let unmatched calls 404 — every
// surface degrades to an honest empty state, and these tests assert on the
// shell (header title + window.location), not on fetched content.

// jsdom does not implement IntersectionObserver, but framer-motion's
// `whileInView` (used by <Reveal>) registers one on mount. Same no-op stub as
// Dashboard.test.tsx — these tests mount whole tabs, reveals included.
beforeAll(() => {
  if (typeof globalThis.IntersectionObserver === "undefined") {
    globalThis.IntersectionObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    } as unknown as typeof IntersectionObserver;
  }
});

const CHARIZARD = {
  id: "base1-4",
  name: "Charizard",
  number: "4",
  rarity: "Rare Holo",
  set_id: "base1",
  set_name: "Base",
  image_small: null,
  image_large: null,
};

// An empty-but-well-formed portfolio: these tests assert on the shell, so the
// surfaces underneath only need to render without throwing. Zeros here are the
// honest empty state, not fabricated value.
const EMPTY_PORTFOLIO = {
  summary: {
    market_value: 0,
    cost_basis: 0,
    unrealized: 0,
    unpriced_items: 0,
    priced_items: 0,
    allocation: [],
    top_gainers: [],
    top_losers: [],
  },
  items: [],
};

const EMPTY_SET_COMPLETION = {
  id: "base1",
  name: "Base",
  series: "Base",
  release_date: null,
  total: 102,
  printed_total: 102,
  cards: [],
  summary: {
    owned: 0,
    checklist_size: 102,
    missing: 102,
    pct_complete: 0,
    est_cost_to_complete: null,
    unpriced_missing: 102,
  },
};

function stubFetch() {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/alerts/unread-count")) {
      return { ok: true, status: 200, json: async () => ({ count: 0 }) };
    }
    // Catalog search (the command palette): GET /cards?name=…
    if (u.includes("/cards?") && u.includes("name=")) {
      return { ok: true, status: 200, json: async () => [CHARIZARD] };
    }
    // The /cards/{id}/… sub-resources must all be matched BEFORE the bare
    // /cards/{id} card fetch, or that branch swallows them and hands each
    // consumer a card payload with none of the fields it reads.
    if (u.includes("/prices/history")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ card_id: "base1-4", variant: "normal", points: [] }),
      };
    }
    if (u.includes("/listings")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ listings: [], listings_unavailable: true }),
      };
    }
    if (u.includes("/sold-comps")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "normal",
          sold_comps: [],
          sold_comps_unavailable: true,
          sold_comps_empty: true,
        }),
      };
    }
    if (u.includes("/deals")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "normal",
          listings_unavailable: true,
          listings_empty: true,
          deals: [],
          thresholds: {
            deal_rip_min_abs: 0,
            deal_rip_min_pct: 0,
            deal_flip_min_abs: 0,
          },
        }),
      };
    }
    if (u.includes("/grading-upside")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "normal",
          raw_price: null,
          psa9: null,
          psa10: null,
          grading_fee: 25,
          upside_to_10: null,
          graded_prices_unavailable: true,
        }),
      };
    }
    // 204 = "no price": the honest null, never a fabricated $0.
    if (u.includes("/price")) {
      return { ok: true, status: 204, json: async () => null };
    }
    if (u.includes("/grade-label")) {
      return { ok: false, status: 404, json: async () => ({}) };
    }
    if (u.includes("/cards/")) {
      return { ok: true, status: 200, json: async () => CHARIZARD };
    }
    if (u.includes("/collection/portfolio")) {
      return { ok: true, status: 200, json: async () => EMPTY_PORTFOLIO };
    }
    // GET /sets?… is the set list; GET /sets/{id} is one set's completion.
    if (u.includes("/sets?")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    if (u.includes("/sets/")) {
      return { ok: true, status: 200, json: async () => EMPTY_SET_COMPLETION };
    }
    if (u.includes("/alerts")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

/** Boot the app at a URL, the way a reload or a home-screen shortcut would. */
function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  return render(
    <ToastProvider>
      <App />
    </ToastProvider>,
  );
}

/** The shell's header title is the single honest read-out of the active view. */
function activeTitle(container: HTMLElement): string {
  return container.querySelector(".app-header h1")?.textContent ?? "";
}

describe("URL routing", () => {
  it("boots on Home when there is no query", () => {
    stubFetch();
    const { container } = renderAt("/");

    expect(activeTitle(container)).toBe("Home");
    expect(window.location.search).toBe("");
  });

  // The live bug: manifest.webmanifest ships these two shortcut URLs, and
  // before routing existed BOTH silently landed on Home.
  it("honours the manifest's ?view=scan shortcut", () => {
    stubFetch();
    const { container } = renderAt("/?view=scan");

    expect(activeTitle(container)).toBe("Scan");
  });

  it("honours the manifest's legacy ?view=portfolio shortcut", async () => {
    stubFetch();
    const { container } = renderAt("/?view=portfolio");

    expect(activeTitle(container)).toBe("Vault");
    // …and rewrites it to the canonical tab id in place, so the alias is not
    // left behind as a Back target.
    await waitFor(() => expect(window.location.search).toBe("?view=vault"));
  });

  it("falls back to Home for an unknown view and cleans the URL", async () => {
    stubFetch();
    const { container } = renderAt("/?view=nonsense");

    expect(activeTitle(container)).toBe("Home");
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("writes the tab to the URL when a nav tab is tapped", () => {
    stubFetch();
    const { container } = renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: "Vault" }));

    expect(activeTitle(container)).toBe("Vault");
    expect(window.location.search).toBe("?view=vault");
  });

  it("restores the current view on reload", () => {
    stubFetch();
    const first = renderAt("/");
    fireEvent.click(screen.getByRole("button", { name: "Sets" }));
    expect(window.location.search).toBe("?view=sets");
    first.unmount();

    // A reload is a fresh mount at whatever URL the address bar holds.
    const { container } = render(
      <ToastProvider>
        <App />
      </ToastProvider>,
    );
    expect(activeTitle(container)).toBe("Sets");
  });

  it("walks back and forward through tabs", async () => {
    stubFetch();
    const { container } = renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: "Vault" }));
    fireEvent.click(screen.getByRole("button", { name: "Browse" }));
    expect(activeTitle(container)).toBe("Browse");

    window.history.back();
    await waitFor(() => expect(activeTitle(container)).toBe("Vault"));

    window.history.back();
    await waitFor(() => expect(activeTitle(container)).toBe("Home"));

    window.history.forward();
    await waitFor(() => expect(activeTitle(container)).toBe("Vault"));
  });
});

describe("card detail routing", () => {
  /** Open a card the way a user does: ⌘K → search → pick a result. */
  async function openCardViaPalette() {
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByLabelText("Command palette search");
    fireEvent.change(input, { target: { value: "charizard" } });
    const result = await screen.findByRole("button", { name: /Charizard/ });
    fireEvent.click(result);
  }

  it("puts the open card in the URL", async () => {
    stubFetch();
    const { container } = renderAt("/?view=vault");

    await openCardViaPalette();

    expect(activeTitle(container)).toBe("Card");
    expect(window.location.search).toBe("?view=vault&card=base1-4");
  });

  it("closes the card on browser Back, returning to the tab underneath", async () => {
    stubFetch();
    const { container } = renderAt("/?view=vault");

    await openCardViaPalette();
    expect(activeTitle(container)).toBe("Card");

    window.history.back();

    await waitFor(() => expect(activeTitle(container)).toBe("Vault"));
    expect(window.location.search).toBe("?view=vault");
  });

  it("closes the card on the in-app Back button", async () => {
    stubFetch();
    const { container } = renderAt("/?view=vault");

    await openCardViaPalette();
    fireEvent.click(await screen.findByRole("button", { name: /← Back/ }));

    await waitFor(() => expect(activeTitle(container)).toBe("Vault"));
    expect(window.location.search).toBe("?view=vault");
  });

  it("deep-links straight to a card, variant included", () => {
    stubFetch();
    const { container } = renderAt("/?view=alerts&card=base1-4&variant=holofoil");

    expect(activeTitle(container)).toBe("Card");
  });

  // A deep-linked card has no app history entry behind it, so Back must rewrite
  // to the tab in place rather than stepping out of the app entirely.
  it("backs out of a deep-linked card without leaving the app", async () => {
    stubFetch();
    const { container } = renderAt("/?view=vault&card=base1-4");

    fireEvent.click(await screen.findByRole("button", { name: /← Back/ }));

    await waitFor(() => expect(activeTitle(container)).toBe("Vault"));
    expect(window.location.search).toBe("?view=vault");
  });

  it("closing the card from a set returns to the set, not the tab", async () => {
    stubFetch();
    const { container } = renderAt("/?view=sets&set=base1");
    expect(activeTitle(container)).toBe("Sets");

    await openCardViaPalette();
    expect(window.location.search).toBe("?view=sets&set=base1&card=base1-4");

    fireEvent.click(await screen.findByRole("button", { name: /← Back/ }));

    // Still on the set detail (the set survives the card closing), and the
    // header keeps reading "Sets" for it.
    await waitFor(() => expect(window.location.search).toBe("?view=sets&set=base1"));
    expect(activeTitle(container)).toBe("Sets");
  });

  it("tapping the active tab closes an open card", async () => {
    stubFetch();
    renderAt("/?view=vault");

    await openCardViaPalette();
    expect(window.location.search).toBe("?view=vault&card=base1-4");

    fireEvent.click(screen.getByRole("button", { name: "Vault" }));

    expect(window.location.search).toBe("?view=vault");
  });
});
