import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import type { GradingLabel, RecognizeResponse } from "../api/types";
import ScanResult from "../components/ScanResult";

function response(overrides: Partial<RecognizeResponse> = {}): RecognizeResponse {
  return {
    status: "confident",
    confidence: 0.94,
    visual_margin: 0.21,
    card: {
      id: "base1-4",
      name: "Charizard",
      number: "4",
      rarity: "Rare Holo",
      set_id: "base1",
      set_name: "Base",
      image_small: null,
      image_large: null,
    },
    // Supplied so PriceLine settles without a network call.
    price: {
      source: "tcgplayer",
      variant: "holofoil",
      low: null,
      mid: null,
      high: null,
      market: 800.0,
      source_updated_at: "2026/07/29",
    },
    candidates: [],
    collector_number_read: "4/102",
    centering: null,
    ...overrides,
  };
}

const noop = () => {};

// A fetch stub that routes by URL substring: 404 for /grade-label (no label yet),
// and the GradingUpside spread for /grading-upside. Mirrors PortfolioView.test.tsx.
function stubFetch(label: GradingLabel | null = null) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/grade-label")) {
      if (label === null) return { ok: false, status: 404, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => label };
    }
    if (u.includes("/grading-upside")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "holofoil",
          raw_price: { market: 120.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
          psa9: { market: 350.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
          psa10: { market: 1200.0, source: "pkmnprices", source_updated_at: "2026/07/28" },
          grading_fee: 25.0,
          upside_to_10: 1055.0,
          graded_prices_unavailable: false,
        }),
      };
    }
    if (u.includes("/authenticity")) {
      // The AuthenticityPanel also fetches from ScanResult; return a clean
      // match payload so the panel renders without an error state in these
      // grading-focused tests.
      return {
        ok: true,
        status: 200,
        json: async () => ({
          caveat: "guide, not a verdict",
          consistency: {
            printed_number: "4",
            catalog_number: "4",
            card_id: "base1-4",
            card_name: "Charizard",
            match: "match",
            note: "matches",
          },
          checklist: [],
        }),
      };
    }
    if (u.includes("/sold-comps")) {
      // ProofOfSales (roadmap row 16) fetches card sold-comps from ScanResult.
      // Return an honest empty (key set, no recent sales) so the block settles
      // cleanly in these grading-focused tests instead of hanging on loading.
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "holofoil",
          sold_comps: [],
          sold_comps_unavailable: false,
          sold_comps_empty: true,
        }),
      };
    }
    if (u.includes("/trade-up")) {
      // Row 19 trade-up simulator — a full assessment so the panel renders
      // cleanly instead of an error state alongside the grading surfaces.
      return {
        ok: true,
        status: 200,
        json: async () => ({
          card_id: "base1-4",
          variant: "holofoil",
          grader: "PSA",
          target_grade: 10,
          raw_leg: { label: "Sell raw now", gross: 119.0, fee: 15.47, net: 103.53, source: "ebay_sold_median", source_updated_at: null, evidence_count: 3, note: "Median of 3 sales." },
          grade_leg: { label: "Grade to PSA 10, then sell", gross: 1200.0, fee: 181.0, net: 1019.0, source: "pkmnprices", source_updated_at: "2026/07/28", evidence_count: null, note: "Graded market." },
          market_reference: 120.0,
          market_reference_source: "tcgplayer",
          market_reference_source_updated_at: "2026/07/29",
          recommendation: "grade",
          recommendation_note: "Grading nets more.",
          centering_cap: null,
          centering_blocks_grading: false,
          caveats: ["Net figures subtract an estimated selling fee."],
        }),
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

const existingLabel: GradingLabel = {
  id: 7,
  scan_id: 42,
  card_id: "base1-4",
  variant: "holofoil",
  grade: 9,
  grader: "PSA",
  cert_number: "12345678",
  notes: "Clean surface",
  created_at: "2026-07-30T12:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("ScanResult grading annotation", () => {
  it("renders the 'Record this card's grade' form when a card is present and scanId is non-null", async () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/record this card's grade/i);
    });
    expect(container.querySelector(".grading-label-form")).not.toBeNull();
    // The grader select and grade input are present.
    expect(container.querySelector(".grading-label-form select")).not.toBeNull();
    expect(container.querySelector('.grading-label-form input[type="number"]')).not.toBeNull();
  });

  it("does NOT render the form when scanId is null (cannot label an unlogged scan)", () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={null}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    expect(container.querySelector(".grading-label-form")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/record this card's grade/i);
  });

  it("does NOT render the form when the card is null (not_found)", () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response({ status: "not_found", card: null })}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    expect(container.querySelector(".grading-label-form")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/record this card's grade/i);
  });

  it("POSTs to /scans/{id}/grade-label with the right JSON body on valid submit", async () => {
    const spy = stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector(".grading-label-form")).not.toBeNull();
    });

    // Fill in grade = 9, grader defaults to PSA, cert + notes optional.
    const gradeInput = container.querySelector(
      '.grading-label-form input[type="number"]',
    ) as HTMLInputElement;
    fireEvent.change(gradeInput, { target: { value: "9" } });

    const submitButton = [...container.querySelectorAll("button")].find((b) =>
      /record grade/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(submitButton).toBeDefined();
    fireEvent.click(submitButton);

    await waitFor(() => {
      // Find the POST call to /scans/42/grade-label
      const post = spy.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/scans/42/grade-label") && (init as RequestInit)?.method === "POST",
      );
      expect(post).toBeDefined();
    });

    const post = spy.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/scans/42/grade-label") && (init as RequestInit)?.method === "POST",
    ) as unknown as [string, RequestInit];
    expect(post).toBeDefined();
    const body = JSON.parse((post[1] as RequestInit).body as string);
    expect(body.grade).toBe(9);
    expect(body.grader).toBe("PSA");
    // Empty cert/notes become null, never empty strings.
    expect(body.cert_number).toBeNull();
    expect(body.notes).toBeNull();
  });

  it("shows the existing label read-only instead of the form when getGradeLabel returns one", async () => {
    stubFetch(existingLabel);

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/recorded grade/i);
    });
    // The form is replaced by the read-only display.
    expect(container.querySelector(".grading-label-form")).toBeNull();
    expect(container.querySelector(".grading-label-display")).not.toBeNull();
    const text = container.textContent ?? "";
    expect(text).toContain("PSA");
    expect(text).toContain("9");
    expect(text).toContain("12345678");
    expect(text).toContain("Clean surface");
  });

  it("renders the GradingUpside panel when a card is present", async () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector(".grading-upside")).not.toBeNull();
    });
    // The spread headline carries the "not a prediction" caveat.
    expect(container.textContent ?? "").toMatch(/spread, not a prediction/i);
  });

  it("renders the GradingStudio when a card is present", async () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector(".grading-studio")).not.toBeNull();
    });
    // centering is null in response() -> studio shows "unmeasured".
    expect(container.textContent ?? "").toMatch(/unmeasured/i);
  });
});

describe("ScanResult proof of sales (roadmap row 16)", () => {
  // A stub that returns real sold comps for /sold-comps (and the same honest
  // defaults the grading tests use for the other ScanResult surfaces).
  function stubFetchWithComps() {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.includes("/sold-comps")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            card_id: "base1-4",
            variant: "holofoil",
            sold_comps: [
              { listing_id: "s1", title: "Charizard #4", price: 812.0, currency: "USD",
                url: "https://ebay.example/s1", condition: "Used", sold_at: "2026-07-30T18:30:00Z", source: "ebay" },
            ],
            sold_comps_unavailable: false,
            sold_comps_empty: false,
          }),
        };
      }
      if (u.includes("/grade-label")) return { ok: false, status: 404, json: async () => ({}) };
      if (u.includes("/grading-upside")) {
        return { ok: true, status: 200, json: async () => ({
          card_id: "base1-4", variant: "holofoil",
          raw_price: { market: 800.0, source: "tcgplayer", source_updated_at: "2026/07/29" },
          psa9: null, psa10: null, grading_fee: 25.0, upside_to_10: null,
          graded_prices_unavailable: true,
        }) };
      }
      if (u.includes("/authenticity")) {
        return { ok: true, status: 200, json: async () => ({
          caveat: "guide, not a verdict",
          consistency: { printed_number: "4", catalog_number: "4", card_id: "base1-4",
            card_name: "Charizard", match: "match", note: "matches" },
          checklist: [],
        }) };
      }
      if (u.includes("/trade-up")) {
        // Row 19 — clean assessment so the panel doesn't error in these tests.
        return { ok: true, status: 200, json: async () => ({
          card_id: "base1-4", variant: "holofoil", grader: "PSA", target_grade: 10,
          raw_leg: { label: "Sell raw now", gross: 812.0, fee: 105.56, net: 706.44, source: "ebay_sold_median", source_updated_at: null, evidence_count: 1, note: "Median of 1 sale." },
          grade_leg: { label: "Grade to PSA 10, then sell", gross: null, fee: null, net: null, source: null, source_updated_at: null, evidence_count: null, note: "No graded price." },
          market_reference: 800.0, market_reference_source: "tcgplayer", market_reference_source_updated_at: "2026/07/29",
          recommendation: "sell_raw", recommendation_note: "Only the sell-raw leg could be estimated.",
          centering_cap: null, centering_blocks_grading: false,
          caveats: ["Net figures subtract an estimated selling fee."],
        }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);
    return spy;
  }

  it("renders proven sales under the price when a card is recognized", async () => {
    stubFetchWithComps();
    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("$812.00");
    });
    expect(container.textContent ?? "").toMatch(/proven sales/i);
    // listed-vs-proven caveat is present (the honesty point of the feature)
    expect(container.textContent ?? "").toMatch(/listed estimate.*actual eBay sales/i);
    // the external sale link opens safely in a new tab
    const link = container.querySelector(".proof-link") as HTMLAnchorElement;
    expect(link).not.toBeNull();
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });

  it("does not render proven sales when no card was recognized (not_found)", async () => {
    stubFetchWithComps();
    const { container } = render(
      <ScanResult
        result={response({ status: "not_found", card: undefined, candidates: [] })}
        variant="holofoil"
        scanId={null}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );
    // ProofOfSales is card-gated; with no card the block never mounts, so the
    // fetcher is never called and no proof heading appears.
    expect(container.textContent ?? "").not.toMatch(/proven sales/i);
    expect(container.querySelector(".proof-of-sales")).toBeNull();
  });
});