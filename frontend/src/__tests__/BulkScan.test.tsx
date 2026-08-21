import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { BatchRecognizeResponse, RecognizeResponse } from "../api/types";
import App from "../App";

// Mirrors the real test pattern (ScanResultGrading.test.tsx, PortfolioView.test.tsx):
// stub global.fetch and route by URL substring. The client module is NOT mocked
// — every client fn (batchRecognize, recordScan, addToCollection, …) flows
// through this fetch stub, so the batch call is intercepted here.

const CONFIDENT: RecognizeResponse = {
  status: "confident",
  confidence: 0.9,
  visual_margin: 0.1,
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
  price: null,
  candidates: [],
  collector_number_read: "4",
  centering: null,
  rectified_path: null,
};

const NOT_FOUND: RecognizeResponse = {
  status: "not_found",
  confidence: 0.0,
  visual_margin: 0.0,
  card: null,
  price: null,
  candidates: [],
  collector_number_read: null,
  centering: null,
  rectified_path: null,
};

// Module-level batch response so individual tests can override it before drive.
let batchResponse: BatchRecognizeResponse = {
  batch_id: "b1",
  count: 0,
  results: [],
};

function setBatch(results: RecognizeResponse[]) {
  batchResponse = { batch_id: "b1", count: results.length, results };
}

function stubFetch() {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    // Bulk recognition — the call under test.
    if (u.includes("/recognize/batch")) {
      return { ok: true, status: 200, json: async () => batchResponse };
    }
    // Per-card scan logging (recordScan) — returns a Scan row.
    if (u.includes("/scans") && u.includes("batch_id")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 1,
          status: "confident",
          predicted_card_id: "base1-4",
          corrected_card_id: null,
          confirmed: false,
          confidence: 0.9,
          visual_margin: 0.1,
          collector_number_read: "4",
        }),
      };
    }
    // Existing single-card scan logging (not used in bulk, but kept for safety).
    // Authenticity panel — a clean no_card payload so it renders without error
    // in these batch-focused tests (the /scans branch below would otherwise match
    // /scans/{id}/authenticity and return a Scan-shaped body with no consistency).
    if (u.includes("/authenticity")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          caveat: "guide, not a verdict",
          consistency: {
            printed_number: null,
            catalog_number: null,
            card_id: null,
            card_name: null,
            match: "no_card",
            note: "No card recognized.",
          },
          checklist: [],
        }),
      };
    }
    if (u.includes("/scans")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 2,
          status: "confident",
          predicted_card_id: null,
          corrected_card_id: null,
          confirmed: false,
          confidence: 0.9,
          visual_margin: 0.1,
          collector_number_read: null,
        }),
      };
    }
    // Collection add — empty 200 is fine.
    if (u.includes("/collection")) {
      return { ok: true, status: 200, json: async () => ({}) };
    }
    // Alerts feed + unread badge (AppShell mounts on the Alerts tab).
    if (u.includes("/alerts/unread-count")) {
      return { ok: true, status: 200, json: async () => ({ count: 0 }) };
    }
    if (u.includes("/alerts")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    // Grade label — 404 = "no label yet" (the common case).
    if (u.includes("/grade-label")) {
      return { ok: false, status: 404, json: async () => ({}) };
    }
    // Grading upside — all-null spread, never a fabricated $0.
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
    // Resolved price + refresh — 204 = "no price" (honest null, never $0).
    if (u.includes("/price") || u.includes("/prices/refresh")) {
      return { ok: true, status: 204, json: async () => null };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

// Drive the bulk capture exactly as the real component allows in jsdom:
// getUserMedia is absent, so CameraCapture renders its error fallback with a
// file <input>. Setting its files and firing change triggers onCapture → the
// bulk recognition path. This is the same mechanism a user uploading a photo
// uses in-browser.
async function driveBulkCapture(container: HTMLElement) {
  await waitFor(() => {
    expect(container.querySelector('input[type="file"]')).not.toBeNull();
  });
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["x"], "page.jpg", { type: "image/jpeg" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Bulk scan mode", () => {
  beforeEach(() => {
    setBatch([]);
  });

  it("renders a bulk-mode toggle in the Scan pane", async () => {
    stubFetch();
    render(<App />);

    // Land on the Scan tab (AppShell defaults to Alerts).
    fireEvent.click(screen.getByRole("button", { name: "Scan" }));

    expect(screen.getByRole("button", { name: /bulk/i })).toBeDefined();
  });

  it("renders N result cells for a batch of N", async () => {
    const spy = stubFetch();
    setBatch([CONFIDENT, NOT_FOUND]);
    const { container } = render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Scan" }));
    fireEvent.click(screen.getByRole("button", { name: /bulk/i }));

    await driveBulkCapture(container);

    await waitFor(() => {
      expect(spy.mock.calls.some(([url]) => String(url).includes("/recognize/batch"))).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByText("Charizard")).toBeDefined();
      expect(screen.getByText(/no card found/i)).toBeDefined();
    });
  });

  it("never shows $0.00 for an unpriced confident card", async () => {
    stubFetch();
    setBatch([CONFIDENT]);
    const { container } = render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Scan" }));
    fireEvent.click(screen.getByRole("button", { name: /bulk/i }));

    await driveBulkCapture(container);

    await waitFor(() => {
      expect(screen.getByText("Charizard")).toBeDefined();
    });
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("$0.00");
  });

  it("bulk-adds confident cards to the collection", async () => {
    const spy = stubFetch();
    setBatch([CONFIDENT, NOT_FOUND]);
    const { container } = render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Scan" }));
    fireEvent.click(screen.getByRole("button", { name: /bulk/i }));

    await driveBulkCapture(container);
    await waitFor(() => expect(screen.getByText("Charizard")).toBeDefined());

    const addAll = screen.getByRole("button", { name: /add all to collection/i });
    fireEvent.click(addAll);

    await waitFor(() => {
      expect(
        spy.mock.calls.some(
          ([url, init]) =>
            String(url).includes("/collection") && (init as RequestInit)?.method === "POST",
        ),
      ).toBe(true);
    });
  });
});