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
});