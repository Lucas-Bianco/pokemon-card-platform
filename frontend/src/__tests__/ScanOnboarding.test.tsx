import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import AppShell, { type ScanFlow } from "../components/AppShell";
import { ToastProvider } from "../components/Toast";
import type { RecognizeResponse } from "../api/types";
import { WELCOME_SEEN_KEY, FIRST_SCAN_DONE_KEY } from "../lib/welcome";

// First-run affordances that live on the Scan pane: a "point at a card" hint
// caption (shows until the first scan→add) and a one-time "Added to your Vault"
// bridge toast. Both retire once FIRST_SCAN_DONE_KEY is written. These render
// AppShell directly with a stub ScanFlow so we exercise the mount-time hint and
// the onConfirm wrapper without the real capture pipeline.

// A confident verdict with no price: ScanResult still fetches the grade-label
// (404 → null, harmless) but skips the sold-comps fetch (price is null), so the
// fetch stub only needs unread-count + grade-label. The "Correct — add to
// collection" button renders for a confident verdict regardless of price.
const CONFIDENT: RecognizeResponse = {
  status: "confident",
  confidence: 0.92,
  visual_margin: 0.3,
  card: {
    id: "base1-4",
    name: "Charizard",
    number: "4",
    rarity: "Rare Holo",
    set_id: "base1",
    set_name: "Base Set",
    image_small: null,
    image_large: null,
  },
  price: null,
  candidates: [],
  collector_number_read: "4",
  centering: null,
  rectified_path: null,
};

/** A no-op ScanFlow with every required field, overridable per test. */
function stubScan(over: Partial<ScanFlow> = {}): ScanFlow {
  return {
    result: null,
    variant: "normal",
    scanId: null,
    busy: false,
    error: null,
    note: null,
    adjusting: false,
    lastImage: null,
    canAdjust: false,
    onCapture: () => {},
    onCorners: () => {},
    onConfirm: () => {},
    onPick: () => {},
    onReject: () => {},
    onRescan: () => {},
    onAdjust: () => {},
    onCancelAdjust: () => {},
    mode: "single",
    onToggleMode: () => {},
    bulk: null,
    ...over,
  };
}

/** Minimal fetch stub: unread-alert count renders the shell; grade-label 404s
 *  to null; everything else degrades to an honest empty 404. */
function stubFetch() {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/alerts/unread-count")) {
      return { ok: true, status: 200, json: async () => ({ count: 0 }) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

/** Render AppShell on the Scan landing, welcome overlay suppressed. */
function renderShell(scan: ScanFlow) {
  window.history.replaceState(null, "", "/?view=scan");
  localStorage.setItem(WELCOME_SEEN_KEY, "1");
  return render(
    <ToastProvider>
      <AppShell scan={scan} appMode="key" onAppModeChange={() => {}} />
    </ToastProvider>,
  );
}

describe("Scan first-run affordances", () => {
  it("shows the 'point at a card' hint before the first scan", () => {
    stubFetch();
    const { container } = renderShell(stubScan());

    expect(container.querySelector(".scan-first-hint")).not.toBeNull();
  });

  it("retires the hint once the first-scan flag is already set", () => {
    stubFetch();
    localStorage.setItem(FIRST_SCAN_DONE_KEY, "1");
    const { container } = renderShell(stubScan());

    expect(container.querySelector(".scan-first-hint")).toBeNull();
  });

  it("fires a one-time 'Added to your Vault' toast on confirm and sets the flag", async () => {
    stubFetch();
    const onConfirm = vi.fn();
    const { container } = renderShell(
      stubScan({ result: CONFIDENT, scanId: 1, onConfirm }),
    );

    const addBtn = [...container.querySelectorAll("button")].find(
      (b) => (b.textContent ?? "").trim() === "Correct — add to collection",
    ) as HTMLElement;
    expect(addBtn).toBeDefined();
    fireEvent.click(addBtn);

    expect(onConfirm).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Added to your Vault");
    });
    expect(localStorage.getItem(FIRST_SCAN_DONE_KEY)).toBe("1");
  });

  it("does not toast again on a subsequent confirm once the flag is set", () => {
    stubFetch();
    localStorage.setItem(FIRST_SCAN_DONE_KEY, "1");
    const onConfirm = vi.fn();
    const { container } = renderShell(
      stubScan({ result: CONFIDENT, scanId: 1, onConfirm }),
    );

    const addBtn = [...container.querySelectorAll("button")].find(
      (b) => (b.textContent ?? "").trim() === "Correct — add to collection",
    ) as HTMLElement;
    fireEvent.click(addBtn);

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(document.body.textContent ?? "").not.toContain("Added to your Vault");
  });
});