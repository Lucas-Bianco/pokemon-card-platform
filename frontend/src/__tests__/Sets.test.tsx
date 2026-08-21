import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import Sets from "../components/Sets";

const noop = () => {};

function stubSets(sets: Array<Record<string, unknown>> = []) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/sets?")) return { ok: true, status: 200, json: async () => sets };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("Sets", () => {
  it("renders the set list with owned/total and a progress bar", async () => {
    stubSets([
      { id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
        total: 2, printed_total: 2, owned: 1, checklist_size: 2, pct_complete: 0.5 },
    ]);
    const { container } = render(<Sets onSelectSet={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    expect(container.textContent ?? "").toContain("1 / 2 owned");
    expect(container.querySelector(".sets-progress-fill")).not.toBeNull();
  });

  it("shows honest 0% for an unowned set, never fabricated", async () => {
    stubSets([
      { id: "promo1", name: "Promo", series: "Promo", release_date: "2020/01/01",
        total: 1, printed_total: 1, owned: 0, checklist_size: 1, pct_complete: 0 },
    ]);
    const { container } = render(<Sets onSelectSet={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("0 / 1 owned");
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("clicking a set calls onSelectSet with the set id", async () => {
    stubSets([
      { id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
        total: 2, printed_total: 2, owned: 0, checklist_size: 2, pct_complete: 0 },
    ]);
    const onSelectSet = vi.fn();
    const { container } = render(<Sets onSelectSet={onSelectSet} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    fireEvent.click(container.querySelector(".sets-row") as HTMLElement);
    expect(onSelectSet).toHaveBeenCalledWith("base1");
  });

  it("renders an empty state when the search matches nothing", async () => {
    const spy = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("q=zzz")) return { ok: true, status: 200, json: async () => [] };
      // mount (no q) returns a set so the empty state only appears for "zzz"
      return {
        ok: true,
        status: 200,
        json: async () => [
          { id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
            total: 2, printed_total: 2, owned: 0, checklist_size: 2, pct_complete: 0 },
        ],
      };
    });
    vi.stubGlobal("fetch", spy);
    const { container } = render(<Sets onSelectSet={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const input = container.querySelector(".sets-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no sets found/i);
    });
  });
});