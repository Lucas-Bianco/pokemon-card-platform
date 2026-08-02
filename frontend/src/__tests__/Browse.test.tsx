import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import Browse from "../components/Browse";

const noop = () => {};

// fetch stub routed by URL substring: /cards?name= returns the given results.
function stubFetch(
  results: Array<{
    id: string;
    name: string;
    set_name: string;
    number: string;
    image_small: string | null;
  }>,
) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/cards?") || u.includes("/cards&")) {
      return { ok: true, status: 200, json: async () => results };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

// The debounce uses a 300ms setTimeout. Fake timers let us assert the catalog
// call has NOT fired immediately after a keystroke; advancing past 300ms fires
// the timer. We then switch to real timers so waitFor can poll for the async
// fetch resolution + React re-render (waitFor relies on real setTimeout).
beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Browse", () => {
  it("shows a hint and does not fetch while the query is empty", () => {
    const spy = stubFetch([]);
    const { container } = render(<Browse onSelectCard={noop} />);

    expect(container.textContent ?? "").toMatch(/search.*cards by name/i);
    // No catalog call fired for an empty query — the backend requires min_length=1.
    expect(spy).not.toHaveBeenCalled();
  });

  it("debounces: typing 'char' surfaces results after the 300ms debounce", async () => {
    const results = [
      { id: "base1-4", name: "Charizard", set_name: "Base", number: "4", image_small: null },
    ];
    const spy = stubFetch(results);

    const { container } = render(<Browse onSelectCard={noop} />);
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    fireEvent.change(input, { target: { value: "char" } });

    // Immediately after typing — no fetch yet (debounce window open).
    expect(spy).not.toHaveBeenCalled();

    // Advance past the debounce to fire the timer, then switch to real timers so
    // the async fetch + React re-render can settle (waitFor polls on real timers).
    vi.advanceTimersByTime(350);
    vi.useRealTimers();

    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    expect(container.textContent ?? "").toContain("Charizard");
    expect(container.textContent ?? "").toContain("Base");
  });

  it("renders an honest 'No cards found' empty state when the search returns nothing", async () => {
    stubFetch([]);

    const { container } = render(<Browse onSelectCard={noop} />);
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "zzzznotacard" } });

    vi.advanceTimersByTime(350);
    vi.useRealTimers();

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/no cards found for/i);
    });
    const text = container.textContent ?? "";
    expect(text).toContain("zzzznotacard");
    // Never fabricate a result.
    expect(container.querySelector(".browse-result")).toBeNull();
  });

  it("calls onSelectCard with the cardId when a result is tapped", async () => {
    const results = [
      { id: "base1-4", name: "Charizard", set_name: "Base", number: "4", image_small: null },
    ];
    stubFetch(results);
    const handleSelect = vi.fn();

    const { container } = render(<Browse onSelectCard={handleSelect} />);
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "char" } });

    vi.advanceTimersByTime(350);
    vi.useRealTimers();

    await waitFor(() => {
      expect(container.querySelector(".browse-result")).not.toBeNull();
    });

    const row = container.querySelector(".browse-result") as HTMLElement;
    fireEvent.click(row);
    expect(handleSelect).toHaveBeenCalledTimes(1);
    expect(handleSelect).toHaveBeenCalledWith({ cardId: "base1-4", variant: undefined });
  });
});