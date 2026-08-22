import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor, fireEvent } from "@testing-library/react";
import SealedCatalog from "../components/SealedCatalog";
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

function stubFetch(opts: { products?: SealedProductsResponse["products"]; status?: number } = {}) {
  const body: SealedProductsResponse = {
    products: opts.products ?? [product(), product({ slug: "sv-etb", name: "Scarlet & Violet Elite Trainer Box", product_type: "etb", msrp: 39.99, print_status: "in_print", era: "Scarlet & Violet", source_url: null })],
    count: opts.products ? opts.products.length : 2,
    product_type: null,
    print_status: null,
  };
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
});