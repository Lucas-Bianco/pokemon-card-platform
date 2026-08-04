import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import SoldComps from "../components/SoldComps";

const comps = [
  { listing_id: "a", title: "Charizard #4", price: 118.0, currency: "USD",
    url: "https://ebay.example/a", condition: "Used", sold_at: "2026-07-30T18:30:00Z", source: "ebay" },
  { listing_id: "b", title: "Charizard #4", price: 121.0, currency: "USD",
    url: "https://ebay.example/b", condition: "Used", sold_at: "2026-07-29T18:30:00Z", source: "ebay" },
];

afterEach(() => vi.unstubAllGlobals());

function stub(body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body }));
}

describe("SoldComps", () => {
  it("renders up to 3 recent sold comps as evidence", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: comps,
          sold_comps_unavailable: false, sold_comps_empty: false });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$118.00");
    });
    expect(container.textContent ?? "").toContain("$121.00");
    expect(container.textContent ?? "").toContain("ebay");
    expect(container.textContent ?? "").toMatch(/recent sold/i);
  });

  it("unavailable -> honest 'set a listings source key' (no fake price)", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: [],
          sold_comps_unavailable: true, sold_comps_empty: false });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/set a listings source key/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("empty -> honest 'no recent sold comps found'", async () => {
    stub({ card_id: "base1-4", variant: "", sold_comps: [],
          sold_comps_unavailable: false, sold_comps_empty: true });
    const { container } = render(<SoldComps cardId="base1-4" variant="" />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no recent sold comps/i);
    });
  });
});