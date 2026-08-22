import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor, fireEvent, act } from "@testing-library/react";
import SealedCatalog from "../components/SealedCatalog";
import { ToastProvider } from "../components/Toast";
import type { SealedProductsResponse } from "../api/types";

function product(over: Partial<SealedProductsResponse["products"][number]> = {}) {
  return {
    slug: "base-booster-pack",
    name: "Base Set Booster Pack",
    era: "Base",
    product_type: "booster_pack" as const,
    msrp: null,
    msrp_currency: "USD",
    print_status: "out_of_print" as const,
    source_url: "https://example.com/base-pack",
    image_url: null,
    released_at: "1999-01-09",
    source: "manual",
    created_at: "2026-08-22T00:00:00Z",
    ...over,
  };
}

const ETB = product({
  slug: "sv-etb",
  name: "Scarlet & Violet Elite Trainer Box",
  product_type: "etb",
  msrp: 39.99,
  print_status: "in_print",
  era: "Scarlet & Violet",
  source_url: null,
});

function marketBody(over: Partial<{
  slug: string;
  name: string;
  msrp: number | null;
  msrp_currency: string;
  market_median: number | null;
  market_source: string | null;
  market_source_updated_at: string | null;
  sold_comps_count: number;
  delta: number | null;
  unavailable: boolean;
  empty: boolean;
}> = {}) {
  return {
    slug: "sv-etb",
    name: "Scarlet & Violet Elite Trainer Box",
    msrp: 39.99,
    msrp_currency: "USD",
    market_median: 40.0,
    market_source: "ebay",
    market_source_updated_at: null,
    sold_comps_count: 3,
    delta: -0.01,
    unavailable: false,
    empty: false,
    ...over,
  };
}

function stubFetch(opts: {
  products?: SealedProductsResponse["products"];
  status?: number;
  market?: ReturnType<typeof marketBody> | null;
  marketStatus?: number;
  logStatus?: number;
} = {}) {
  const body: SealedProductsResponse = {
    products: opts.products ?? [product(), ETB],
    count: opts.products ? opts.products.length : 2,
    product_type: null,
    print_status: null,
  };
  const market = opts.market === undefined ? marketBody() : opts.market;
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/sealed/products?")) {
      // Echo the active type/status filter back so the empty-state test can tell
      // "filtered empty" from "no seed yet".
      const params = new URLSearchParams(u.split("?")[1]);
      const product_type = params.get("type") || null;
      const print_status = params.get("status") || null;
      return {
        ok: (opts.status ?? 200) < 400,
        status: opts.status ?? 200,
        json: async () => ({ ...body, product_type, print_status, count: body.products.length }),
      };
    }
    if (u.includes("/market")) {
      const ok = (opts.marketStatus ?? 200) < 400;
      return {
        ok,
        status: opts.marketStatus ?? 200,
        json: async () => (ok ? market : { detail: "sealed product not found" }),
      };
    }
    if (u.includes("/sealed/ledger/from-catalog")) {
      const ok = (opts.logStatus ?? 201) < 400;
      return {
        ok,
        status: opts.logStatus ?? 201,
        json: async () =>
          ok
            ? { id: 9, query: "Scarlet & Violet Elite Trainer Box", product_type: "etb", quantity: 2, cost_per_unit: 39.99, source: null, listing_url: null, notes: null, bought_at: "", created_at: "" }
            : { detail: "sealed product not found" },
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

describe("SealedCatalog", () => {
  it("renders seeded products with name, era, and MSRP", async () => {
    stubFetch();
    const { container, getByText } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-card")).toBeTruthy());
    expect(getByText("Base Set Booster Pack")).toBeTruthy();
    expect(getByText("Scarlet & Violet Elite Trainer Box")).toBeTruthy();
    // ETB has a known MSRP -> rendered as the real number.
    expect(container.textContent).toMatch(/\$39\.99/);
  });

  it("shows 'no MSRP' (em dash) for null msrp, never $0.00", async () => {
    stubFetch();
    const { container } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-card")).toBeTruthy());
    expect(container.textContent).toMatch(/no MSRP/);
    expect(container.textContent).not.toMatch(/\$0\.00/);
  });

  it("changing the type select changes the fetch params", async () => {
    const spy = stubFetch();
    render(<SealedCatalog />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    const select = document.querySelector('[aria-label="Filter by product type"]') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "etb" } });

    await waitFor(() => {
      const lastUrl = String(spy.mock.calls[spy.mock.calls.length - 1][0]);
      expect(lastUrl).toContain("type=etb");
    });
  });

  it("honest empty state when filtered to nothing", async () => {
    stubFetch({ products: [] });
    const { container } = render(<SealedCatalog />);
    // Set a filter so the body echoes product_type back -> "filtered empty" copy.
    const select = document.querySelector('[aria-label="Filter by product type"]') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "tin" } });
    await waitFor(() => expect(container.textContent).toMatch(/No products match these filters/i));
  });

  it("source link is external with noopener noreferrer", async () => {
    stubFetch();
    const { container } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-source")).toBeTruthy());
    const link = container.querySelector(".sealed-catalog-source") as HTMLAnchorElement;
    expect(link.rel).toBe("noopener noreferrer");
    expect(link.target).toBe("_blank");
    expect(link.href).toBe("https://example.com/base-pack");
  });

  it("Phase C: 'vs market' expands a panel showing MSRP vs median + delta", async () => {
    stubFetch();
    const { container } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-card")).toBeTruthy());

    // The ETB card's "vs market" button (second card).
    const buttons = container.querySelectorAll(".sealed-catalog-action");
    const marketBtn = Array.from(buttons).find(
      (b) => b.textContent === "vs market",
    ) as HTMLButtonElement;
    expect(marketBtn).toBeTruthy();
    await act(async () => { fireEvent.click(marketBtn); });

    await waitFor(() =>
      expect(container.querySelector(".sealed-catalog-market")).toBeTruthy(),
    );
    // MSRP vs median both render; delta is the signed difference.
    expect(container.textContent).toMatch(/\$39\.99/);
    expect(container.textContent).toMatch(/\$40\.00/);
    expect(container.querySelector(".deal-delta-under")).toBeTruthy();
    expect(container.textContent).toMatch(/Sold comps/);
  });

  it("Phase C: unavailable (no key) -> 'set a listings key', never a fabricated median", async () => {
    stubFetch({ market: marketBody({ unavailable: true, empty: false, market_median: null, delta: null, sold_comps_count: 0, market_source: null }) });
    const { container } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-card")).toBeTruthy());

    const marketBtn = Array.from(container.querySelectorAll(".sealed-catalog-action")).find(
      (b) => b.textContent === "vs market",
    ) as HTMLButtonElement;
    await act(async () => { fireEvent.click(marketBtn); });

    await waitFor(() =>
      expect(container.textContent).toMatch(/set a listings key/i),
    );
    // No fabricated $0 median.
    expect(container.textContent).not.toMatch(/\$0\.00/);
  });

  it("Phase C: empty (key set, 0 comps) -> 'no recent sold comps'", async () => {
    stubFetch({ market: marketBody({ unavailable: false, empty: true, market_median: null, delta: null, sold_comps_count: 0, market_source: null }) });
    const { container } = render(<SealedCatalog />);
    await waitFor(() => expect(container.querySelector(".sealed-catalog-card")).toBeTruthy());

    const marketBtn = Array.from(container.querySelectorAll(".sealed-catalog-action")).find(
      (b) => b.textContent === "vs market",
    ) as HTMLButtonElement;
    await act(async () => { fireEvent.click(marketBtn); });

    await waitFor(() =>
      expect(container.textContent).toMatch(/no recent sold comps/i),
    );
  });

  it("Phase B: 'Log to ledger' form POSTs /sealed/ledger/from-catalog with slug + facts", async () => {
    const spy = stubFetch();
    render(
      <ToastProvider>
        <SealedCatalog />
      </ToastProvider>,
    );
    await waitFor(() => expect(spy.mock.calls.some((c) => String(c[0]).includes("/sealed/products?"))).toBeTruthy());

    const logBtn = Array.from(document.querySelectorAll(".sealed-catalog-action")).find(
      (b) => b.textContent === "Log to ledger",
    ) as HTMLButtonElement;
    expect(logBtn).toBeTruthy();
    await act(async () => { fireEvent.click(logBtn); });

    // The form is now open (one per card; use the first card's fields).
    const costInput = document.querySelector(
      '[aria-label="Cost per unit for Base Set Booster Pack"]',
    ) as HTMLInputElement;
    expect(costInput).toBeTruthy();
    await act(async () => {
      fireEvent.change(costInput, { target: { value: "5.00" } });
    });

    const form = document.querySelector(".sealed-catalog-log-form") as HTMLFormElement;
    await act(async () => { fireEvent.submit(form); });

    await waitFor(() => {
      const call = spy.mock.calls.find(
        (c) => String(c[0]).includes("/sealed/ledger/from-catalog"),
      );
      expect(call).toBeTruthy();
      const sent = JSON.parse((call![1]?.body as string) ?? "{}");
      expect(sent.slug).toBe("base-booster-pack");
      expect(sent.quantity).toBe(1);
      expect(sent.cost_per_unit).toBe(5);
    });
  });

  it("Phase B: submit is disabled until a valid cost is entered", async () => {
    stubFetch();
    render(<SealedCatalog />);
    await waitFor(() => expect(document.querySelector(".sealed-catalog-card")).toBeTruthy());

    const logBtn = Array.from(document.querySelectorAll(".sealed-catalog-action")).find(
      (b) => b.textContent === "Log to ledger",
    ) as HTMLButtonElement;
    await act(async () => { fireEvent.click(logBtn); });

    const submit = document.querySelector(".sealed-catalog-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });
});