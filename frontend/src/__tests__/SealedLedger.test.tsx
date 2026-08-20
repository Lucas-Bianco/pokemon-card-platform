import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import SealedLedger from "../components/SealedLedger";
import type { SealedLedgerResponse, SheetsSyncResult, ValuationRefreshResult } from "../api/types";

function baseEntry(over: Partial<SealedLedgerResponse["purchases"][number]> = {}) {
  return {
    id: 1,
    query: "scarlet violet booster box",
    product_type: "booster_box",
    quantity: 2,
    cost_per_unit: 120,
    total_cost: 240,
    source: "eBay",
    listing_url: null,
    notes: null,
    bought_at: "2026-08-19T00:00:00Z",
    created_at: "2026-08-19T00:00:00Z",
    value_per_unit: 150,
    total_current_value: 300,
    profit: 60,
    profit_pct: 0.25,
    market_fetched_at: "2026-08-19T12:00:00Z",
    market_source: "ebay_sold_median",
    valued: true,
    ...over,
  };
}

function stubFetch(opts: {
  ledger?: SealedLedgerResponse;
  refresh?: ValuationRefreshResult;
  sync?: SheetsSyncResult;
  logStatus?: number;
  deleteStatus?: number;
} = {}) {
  const ledger: SealedLedgerResponse = opts.ledger ?? {
    purchases: [baseEntry()],
    listings_unavailable: false,
  };
  const refresh: ValuationRefreshResult = opts.refresh ?? {
    valued: 1, skipped_no_comps: 0, skipped_no_key: false,
  };
  const sync: SheetsSyncResult = opts.sync ?? { synced: true, rows: 1, reason: null };
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/sealed/ledger/valuate") && method === "POST") {
      return { ok: true, status: 200, json: async () => refresh };
    }
    if (u.endsWith("/sealed/ledger/sync") && method === "POST") {
      return { ok: true, status: 200, json: async () => sync };
    }
    if (u.match(/\/sealed\/ledger\/\d+$/) && method === "DELETE") {
      return { ok: (opts.deleteStatus ?? 204) < 400, status: opts.deleteStatus ?? 204, json: async () => ({}) };
    }
    if (u.endsWith("/sealed/ledger") && method === "POST") {
      return { ok: (opts.logStatus ?? 201) < 400, status: opts.logStatus ?? 201, json: async () => ({ id: 99 }) };
    }
    if (u.endsWith("/sealed/ledger")) {
      return { ok: true, status: 200, json: async () => ledger };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

describe("SealedLedger", () => {
  it("renders ledger entries with profit and never $0.00 for unvalued", async () => {
    stubFetch({
      ledger: { purchases: [baseEntry({ valued: false, value_per_unit: null, total_current_value: null, profit: null, profit_pct: null, market_fetched_at: null, market_source: null })], listings_unavailable: false },
    });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    expect(container.textContent).not.toMatch(/\$0\.00/);
    expect(container.textContent).toMatch(/not yet valued/i);
  });

  it("shows an honest empty state when there are no purchases", async () => {
    stubFetch({ ledger: { purchases: [], listings_unavailable: false } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.textContent).toMatch(/no purchases logged/i));
  });

  it("warns when the eBay key is missing on refresh", async () => {
    stubFetch({
      ledger: { purchases: [baseEntry()], listings_unavailable: true },
      refresh: { valued: 0, skipped_no_comps: 0, skipped_no_key: true },
    });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const refreshBtn = [...container.querySelectorAll("button")].find((b) => /refresh/i.test(b.textContent || "")) as HTMLButtonElement;
    expect(refreshBtn).toBeTruthy();
    fireEvent.click(refreshBtn);
    await waitFor(() => expect(container.textContent).toMatch(/set cardplatform_listings_api_key/i));
  });

  it("logs a purchase via the form", async () => {
    const spy = stubFetch();
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const queryInput = container.querySelector('input[name="ledger-query"]') as HTMLInputElement;
    const costInput = container.querySelector('input[name="ledger-cost"]') as HTMLInputElement;
    fireEvent.change(queryInput, { target: { value: "151 booster bundle" } });
    fireEvent.change(costInput, { target: { value: "27.50" } });
    const logBtn = [...container.querySelectorAll("button")].find((b) => /log purchase/i.test(b.textContent || "")) as HTMLButtonElement;
    fireEvent.click(logBtn);
    await waitFor(() => {
      const post = spy.mock.calls.find((c) => (c[1]?.method === "POST") && String(c[0]).endsWith("/sealed/ledger"));
      expect(post).toBeTruthy();
    });
  });

  it("deletes a purchase", async () => {
    const spy = stubFetch();
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const delBtn = container.querySelector(".ledger-delete") as HTMLButtonElement;
    expect(delBtn).toBeTruthy();
    fireEvent.click(delBtn);
    await waitFor(() => {
      const del = spy.mock.calls.find((c) => c[1]?.method === "DELETE");
      expect(del).toBeTruthy();
    });
  });

  it("syncs to Google Sheets and reports rows", async () => {
    stubFetch({ sync: { synced: true, rows: 2, reason: null } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const syncBtn = [...container.querySelectorAll("button")].find((b) => /sync to google/i.test(b.textContent || "")) as HTMLButtonElement;
    expect(syncBtn).toBeTruthy();
    fireEvent.click(syncBtn);
    await waitFor(() => expect(container.textContent).toMatch(/synced 2 row/i));
  });

  it("shows setup instructions when sync is not configured", async () => {
    stubFetch({ sync: { synced: false, rows: 0, reason: "not_configured" } });
    const { container } = render(<SealedLedger />);
    await waitFor(() => expect(container.querySelector(".deal-card")).toBeTruthy());
    const syncBtn = [...container.querySelectorAll("button")].find((b) => /sync to google/i.test(b.textContent || "")) as HTMLButtonElement;
    fireEvent.click(syncBtn);
    await waitFor(() => expect(container.textContent).toMatch(/not configured/i));
  });
});