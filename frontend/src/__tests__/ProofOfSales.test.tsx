import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import ProofOfSales from "../components/ProofOfSales";
import type { ProofOfSalesData } from "../components/ProofOfSales";

const comps = [
  { listing_id: "a", title: "Scarlet & Violet Booster Box", price: 118.0, currency: "USD",
    url: "https://ebay.example/a", condition: "New", sold_at: "2026-07-30T18:30:00Z", source: "ebay" },
  { listing_id: "b", title: "Scarlet & Violet Booster Box", price: 121.0, currency: "USD",
    url: "https://ebay.example/b", condition: "New", sold_at: "2026-07-29T18:30:00Z", source: "ebay" },
];

afterEach(() => vi.restoreAllMocks());

describe("ProofOfSales", () => {
  it("renders proven sales with price, date, and an external link", async () => {
    const data: ProofOfSalesData = { sold_comps: comps, sold_comps_unavailable: false, sold_comps_empty: false };
    const { container } = render(<ProofOfSales fetcher={async () => data} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$118.00");
    });
    expect(container.textContent ?? "").toContain("$121.00");
    expect(container.textContent ?? "").toContain("ebay");
    // listed-vs-proven caveat present (the whole feature's honesty point)
    expect(container.textContent ?? "").toMatch(/listed estimate.*actual eBay sales/i);
    expect(container.textContent ?? "").toMatch(/proven sales/i);
  });

  it("links open in a new tab with rel=noopener (safe external nav)", async () => {
    const data: ProofOfSalesData = { sold_comps: comps, sold_comps_unavailable: false, sold_comps_empty: false };
    const { container } = render(<ProofOfSales fetcher={async () => data} />);
    await waitFor(() => {
      expect(container.querySelector(".proof-link")).not.toBeNull();
    });
    const link = container.querySelector(".proof-link") as HTMLAnchorElement;
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
    expect(link.rel).toContain("noreferrer");
    expect(link.href).toBe("https://ebay.example/a");
  });

  it("unavailable -> honest 'set a listings source key' (no fake price)", async () => {
    const data: ProofOfSalesData = { sold_comps: [], sold_comps_unavailable: true, sold_comps_empty: false };
    const { container } = render(<ProofOfSales fetcher={async () => data} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set a listings source key/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("empty -> honest 'no recent proven sales found'", async () => {
    const data: ProofOfSalesData = { sold_comps: [], sold_comps_unavailable: false, sold_comps_empty: true };
    const { container } = render(<ProofOfSales fetcher={async () => data} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no recent proven sales/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("renders the loading state before the fetcher resolves", () => {
    const data: ProofOfSalesData = { sold_comps: comps, sold_comps_unavailable: false, sold_comps_empty: false };
    const { container } = render(<ProofOfSales fetcher={async () => data} />);
    expect(container.textContent ?? "").toMatch(/checking proven sales/i);
  });
});