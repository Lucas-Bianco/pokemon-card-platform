import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

import type { GradingUpside as GradingUpsideData } from "../api/types";
import GradingUpside from "../components/GradingUpside";

function fullSpread(overrides: Partial<GradingUpsideData> = {}): GradingUpsideData {
  return {
    card_id: "base1-4",
    variant: "holofoil",
    raw_price: { market: 120.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
    psa9: { market: 350.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
    psa10: { market: 1200.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
    grading_fee: 25.0,
    upside_to_10: 1055.0,
    graded_prices_unavailable: false,
    ...overrides,
  };
}

// Stub fetch by URL substring: returns the given body for /grading-upside.
// Mirrors the PortfolioView.test.tsx stubFetch helper.
function stubFetch(body: GradingUpsideData) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/grading-upside")) {
      return { ok: true, status: 200, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("GradingUpside", () => {
  it("renders the full spread: raw, PSA 9, PSA 10, fee, and upside to 10 with .up", async () => {
    stubFetch(fullSpread());

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$120.00");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("$350.00"); // PSA 9
    expect(text).toContain("$1200.00"); // PSA 10 (formatMoney uses toFixed, no comma)
    expect(text).toContain("$25.00"); // fee
    expect(text).toContain("+$1055.00"); // upside to 10
    expect(container.querySelector(".grading-upside-value .up")).not.toBeNull();
    // Sources travel with every figure.
    expect(text).toContain("tcgplayer");
    expect(text).toContain("pkmnprices");
  });

  it("states it is a spread, not a prediction, in the headline", async () => {
    stubFetch(fullSpread());

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$120.00");
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/spread, not a prediction/i);
    expect(text).toMatch(/not a grade prediction/i);
  });

  it("shows the API-key hint and em-dash tiers when graded_prices_unavailable is true", async () => {
    stubFetch(
      fullSpread({
        psa9: null,
        psa10: null,
        upside_to_10: null,
        graded_prices_unavailable: true,
      }),
    );

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/graded prices unavailable/i);
    });
    const text = container.textContent ?? "";
    expect(text).toContain("CARDPLATFORM_GRADED_PRICE_API_KEY");
    // PSA 9 / PSA 10 rows render em dashes, not prices.
    expect(text).not.toContain("$350.00");
    expect(text).not.toContain("$1200.00");
    // Upside is an em dash, never a fake number.
    expect(text).not.toContain("$0.00");
    expect(container.querySelector(".grading-upside-value .unknown")).not.toBeNull();
  });

  it("renders an em dash and 'no market price' for a null raw_price, never $0.00", async () => {
    stubFetch(
      fullSpread({
        raw_price: null,
        upside_to_10: null,
      }),
    );

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no market price/i);
    });
    const text = container.textContent ?? "";
    expect(text).not.toContain("$0.00");
    // Upside null because raw is missing — say so, do not fabricate.
    expect(text).toMatch(/need a raw price to compute the upside to a 10/i);
    expect(container.querySelector(".grading-upside-value .unknown")).not.toBeNull();
  });

  it("shows 'need a PSA 10 sold comp' when only psa9 is present (upside null, graded available)", async () => {
    stubFetch(
      fullSpread({
        psa10: null,
        upside_to_10: null,
      }),
    );

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$350.00"); // psa9 present
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/need a PSA 10 sold comp to compute the upside to a 10/i);
    expect(text).not.toContain("$0.00");
    expect(container.querySelector(".grading-upside-value .unknown")).not.toBeNull();
  });

  it("does not crash during loading and renders a muted note", async () => {
    // A fetch that never resolves keeps the component in the loading state.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {})),
    );

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/checking grading spread/i);
    // No panel rendered yet — loading is honest, not a fake spread.
    expect(container.querySelector(".grading-upside-headline")).toBeNull();
  });

  it("renders an honest error when the request fails, never a fake panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({}) })),
    );

    const { container } = render(<GradingUpside cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/request failed/i);
    });
    // No spread body rendered — an error is honest, a fabricated spread is not.
    expect(container.querySelector(".grading-upside-headline")).toBeNull();
    expect(container.textContent ?? "").not.toContain("$0.00");
  });
});