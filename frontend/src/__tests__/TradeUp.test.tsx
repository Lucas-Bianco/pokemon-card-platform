import { afterEach, describe, expect, it, vi } from "vitest";
import { render, waitFor, fireEvent } from "@testing-library/react";

import type { TradeUpAssessment, TradeUpLeg } from "../api/types";
import TradeUp from "../components/TradeUp";

function leg(over: Partial<TradeUpLeg> = {}): TradeUpLeg {
  return {
    label: "Sell raw now",
    gross: 119.0,
    fee: 15.47,
    net: 103.53,
    source: "ebay_sold_median",
    source_updated_at: null,
    evidence_count: 3,
    note: "Median of 3 recent eBay sale(s), net of ~13% selling fee.",
    ...over,
  };
}

function fullAssessment(over: Partial<TradeUpAssessment> = {}): TradeUpAssessment {
  return {
    card_id: "base1-4",
    variant: "holofoil",
    grader: "PSA",
    target_grade: 10,
    raw_leg: leg({ label: "Sell raw now", gross: 119.0, fee: 15.47, net: 103.53, evidence_count: 3 }),
    grade_leg: leg({
      label: "Grade to PSA 10, then sell",
      gross: 1200.0,
      fee: 181.0,
      net: 1019.0,
      source: "pkmnprices",
      source_updated_at: "2026/07/28",
      evidence_count: null,
      note: "Graded PSA 10 market, net of $25.00 grading fee + ~13% selling fee.",
    }),
    market_reference: 300.0,
    market_reference_source: "tcgplayer",
    market_reference_source_updated_at: "2026/07/29",
    recommendation: "grade",
    recommendation_note: "Grading nets ~$915.47 more than selling raw.",
    centering_cap: null,
    centering_blocks_grading: false,
    caveats: [
      "Net figures subtract an estimated ~13% selling fee.",
      "Proven sales are recent eBay transactions.",
      "Grading outcome is not guaranteed.",
    ],
    ...over,
  };
}

// Stub fetch by URL substring: returns the given body for /trade-up.
function stubFetch(body: TradeUpAssessment) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/trade-up")) {
      return { ok: true, status: 200, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("TradeUp", () => {
  it("renders both legs' net figures + sources + the descriptive read", async () => {
    stubFetch(fullAssessment());

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$103.53"); // raw net
    });
    const text = container.textContent ?? "";
    expect(text).toContain("$1019.00"); // grade net
    expect(text).toContain("$300.00"); // market reference (ask)
    expect(text).toContain("tcgplayer");
    expect(text).toContain("pkmnprices");
    // Descriptive read (grade nets more) -> "Grade, then sell"
    expect(text).toContain("Grade, then sell");
    expect(container.querySelector(".tradeup-recommendation .up")).not.toBeNull();
  });

  it("shows the sell-raw read when selling raw nets more", async () => {
    stubFetch(fullAssessment({
      recommendation: "sell_raw",
      recommendation_note: "Selling raw nets ~$10.00 more than grading.",
    }));

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Sell raw now");
    });
    expect(container.querySelector(".tradeup-recommendation .neutral")).not.toBeNull();
  });

  it("renders an em dash, never $0.00, for an unestimable leg", async () => {
    stubFetch(fullAssessment({
      raw_leg: leg({
        gross: null, fee: null, net: null, source: null,
        evidence_count: 0, note: "No proven eBay sales found.",
      }),
      recommendation: "grade",
      recommendation_note: "Only the grade leg could be estimated.",
    }));

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$1019.00");
    });
    // The raw leg shows an em dash + "no estimate", never a fabricated $0.00.
    const rawLeg = container.querySelectorAll(".tradeup-leg")[0];
    expect(rawLeg?.classList.contains("unpriced")).toBe(true);
    expect(rawLeg?.textContent ?? "").toContain("—");
    expect(rawLeg?.textContent ?? "").toContain("no estimate");
    expect(rawLeg?.textContent ?? "").not.toContain("$0.00");
  });

  it("renders an em dash read when neither leg could be estimated", async () => {
    stubFetch(fullAssessment({
      raw_leg: leg({ gross: null, fee: null, net: null, source: null, evidence_count: 0, note: "No proven sales." }),
      grade_leg: leg({ gross: null, fee: null, net: null, source: null, evidence_count: null, note: "No graded price." }),
      recommendation: null,
      recommendation_note: "Neither leg could be estimated honestly.",
    }));

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Neither leg could be estimated");
    });
    const rec = container.querySelector(".tradeup-recommendation");
    expect(rec?.textContent ?? "").toContain("—");
    expect(rec?.querySelector(".up")).toBeNull();
  });

  it("surfaces the centering-blocks note when the cap rules out the grade", async () => {
    stubFetch(fullAssessment({
      centering_cap: 8,
      centering_blocks_grading: true,
      recommendation: "sell_raw",
      recommendation_note: "Centering rules out the target grade.",
    }));

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("not a real option");
    });
    expect(container.querySelector(".tradeup-block-note")).not.toBeNull();
  });

  it("lists every caveat verbatim", async () => {
    const a = fullAssessment();
    stubFetch(a);

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$1019.00");
    });
    for (const c of a.caveats) {
      expect(container.textContent ?? "").toContain(c);
    }
  });

  it("sends the target grade + centering cap as query params on load + change", async () => {
    const spy = stubFetch(fullAssessment());

    render(<TradeUp cardId="base1-4" variant="holofoil" initialCenteringCap={9} />);

    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    const firstUrl = String(spy.mock.calls[0][0]);
    expect(firstUrl).toContain("grade=10");
    expect(firstUrl).toContain("centering_cap=9");

    // Change the target grade -> a new fetch with the new grade.
    const select = document.querySelector('select[aria-label="Target grade"]') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "9" } });
    await waitFor(() => {
      const lastUrl = String(spy.mock.calls[spy.mock.calls.length - 1][0]);
      expect(lastUrl).toContain("grade=9");
    });
  });

  it("does not send centering_cap when the box is blank (centering unmeasured)", async () => {
    const spy = stubFetch(fullAssessment());

    render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    const url = String(spy.mock.calls[0][0]);
    expect(url).not.toContain("centering_cap");
  });

  it("shows an honest error, never a fake panel, when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));

    const { container } = render(<TradeUp cardId="base1-4" variant="holofoil" />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    // No fabricated leg figures on error.
    expect(container.querySelector(".tradeup-legs")).toBeNull();
  });

  it("pre-fills the centering cap from initialCenteringCap", () => {
    stubFetch(fullAssessment());
    render(<TradeUp cardId="base1-4" variant="holofoil" initialCenteringCap={8} />);
    const input = document.querySelector('input[aria-label="Centering cap"]') as HTMLInputElement;
    expect(input.value).toBe("8");
  });
});