import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import type { InsuranceValue } from "../api/types";
import InsuranceValuePanel from "../components/InsuranceValue";

function insurance(over: Partial<InsuranceValue> = {}): InsuranceValue {
  return {
    conservative: 90.0,
    median: 100.0,
    aggressive: 120.0,
    priced_items: 1,
    unpriced_items: 1,
    schedule: [
      {
        card_id: "base1-4",
        card_name: "Charizard",
        set_name: "Base",
        variant: "holofoil",
        quantity: 2,
        low: 90.0,
        market: 100.0,
        high: 120.0,
        source: "tcgplayer",
        source_updated_at: "2026/07/29",
        priced: true,
      },
      {
        card_id: "base1-58",
        card_name: "Pikachu",
        set_name: "Base",
        variant: "normal",
        quantity: 1,
        low: null,
        market: null,
        high: null,
        source: null,
        source_updated_at: null,
        priced: false,
      },
    ],
    caveat: "An indicative estimate, not a binding appraisal.",
    ...over,
  };
}

function stubFetch(body: InsuranceValue) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/collection/insurance")) {
      return { ok: true, status: 200, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("InsuranceValue", () => {
  it("renders the three replacement-value bands", async () => {
    stubFetch(insurance());
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("$90.00"); // conservative
    expect(text).toContain("$100.00"); // median
    expect(text).toContain("$120.00"); // aggressive
  });

  it("notes unpriced cards are excluded, never guessed at $0", async () => {
    stubFetch(insurance());
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/never guessed/i);
    });
    expect(container.textContent ?? "").toContain("1 priced / 1 unpriced");
  });

  it("omits the 'never guessed' note when everything is priced", async () => {
    stubFetch(insurance({ unpriced_items: 0, priced_items: 2 }));
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    expect(container.textContent ?? "").not.toMatch(/never guessed/i);
    expect(container.textContent ?? "").toContain("2 priced / 0 unpriced");
  });

  it("hides the schedule by default and reveals it on toggle", async () => {
    stubFetch(insurance());
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    expect(container.querySelector(".insurance-schedule")).toBeNull();

    const toggle = [...container.querySelectorAll("button")].find((b) =>
      /view printable schedule/i.test(b.textContent ?? ""),
    );
    expect(toggle).toBeDefined();
    fireEvent.click(toggle as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".insurance-schedule")).not.toBeNull();
    });
    // Both priced and unpriced holdings appear in the schedule.
    const rows = container.querySelectorAll(".insurance-schedule tbody tr");
    expect(rows.length).toBe(2);
  });

  it("shows a Print button when the schedule is open", async () => {
    stubFetch(insurance());
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    const toggle = [...container.querySelectorAll("button")].find((b) =>
      /view printable schedule/i.test(b.textContent ?? ""),
    );
    fireEvent.click(toggle as HTMLButtonElement);
    await waitFor(() => {
      expect(container.querySelector(".insurance-print")).not.toBeNull();
    });
    expect(container.querySelector(".insurance-print")?.textContent).toMatch(/print/i);
  });

  it("renders an em dash, never $0.00, for an unpriced schedule line", async () => {
    stubFetch(insurance());
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    fireEvent.click(
      [...container.querySelectorAll("button")].find((b) =>
        /view printable schedule/i.test(b.textContent ?? ""),
      ) as HTMLButtonElement,
    );
    await waitFor(() => {
      expect(container.querySelector(".insurance-schedule")).not.toBeNull();
    });
    const unpricedRow = container.querySelector(".insurance-schedule tr.unpriced");
    expect(unpricedRow).not.toBeNull();
    // The unpriced row's low/market/high cells are em dashes, not dressed-up zeros.
    expect(unpricedRow?.textContent ?? "").toContain("—");
    expect(unpricedRow?.textContent ?? "").not.toContain("$0.00");
  });

  it("renders honest $0.00 bands for an empty collection (nothing to value)", async () => {
    stubFetch(
      insurance({
        conservative: 0,
        median: 0,
        aggressive: 0,
        priced_items: 0,
        unpriced_items: 0,
        schedule: [],
      }),
    );
    const { container } = render(<InsuranceValuePanel />);
    await waitFor(() => {
      expect(container.querySelector(".insurance-bands")).not.toBeNull();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("$0.00"); // genuine zero — honest, not fabricated
    expect(text).toContain("0 priced / 0 unpriced");
  });
});