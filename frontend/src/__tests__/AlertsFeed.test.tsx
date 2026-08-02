import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import AlertsFeed from "../components/AlertsFeed";
import type { AlertEvent } from "../api/types";

const noop = () => {};

// Three events covering the restock / price_target / drop_time chips. The
// first is unread (read_at null) and 3 minutes old; the second is read and 2
// hours old; the third is an unread no-card drop reminder 1 day old. Times
// are computed relative to now so the relative-time formatter stays stable.
function sampleEvents(): AlertEvent[] {
  const now = Date.now();
  return [
    {
      id: 1,
      watch_id: 10,
      card_id: "base1-4",
      alert_type: "restock",
      message: "Charizard is back in stock",
      context: null,
      delivered_push: false,
      delivered_email: false,
      read_at: null,
      created_at: new Date(now - 3 * 60 * 1000).toISOString(),
    },
    {
      id: 2,
      watch_id: 11,
      card_id: "base1-4",
      alert_type: "price_target",
      message: "Charizard hit your target",
      context: null,
      delivered_push: true,
      delivered_email: false,
      read_at: "2026-07-30T00:00:00Z",
      created_at: new Date(now - 2 * 60 * 60 * 1000).toISOString(),
    },
    {
      id: 3,
      watch_id: 12,
      card_id: null,
      alert_type: "drop_time",
      message: "Pokemon Center drop soon",
      context: null,
      delivered_push: false,
      delivered_email: false,
      read_at: null,
      created_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    },
  ];
}

// fetch stub routed by URL substring: GET /alerts → events; PATCH /alerts/{id}
// → the updated event with read_at set; POST /alerts/read-all → {updated}.
function stubFetch(events: AlertEvent[]) {
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/alerts/unread-count")) {
      const count = events.filter((e) => e.read_at === null).length;
      return { ok: true, status: 200, json: async () => ({ count }) };
    }
    if (u.includes("/alerts/read-all") && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ updated: events.filter((e) => e.read_at === null).length }) };
    }
    if (u.match(/\/alerts\/\d+$/) && method === "PATCH") {
      const id = Number(u.match(/\/alerts\/(\d+)$/)![1]);
      const evt = events.find((e) => e.id === id)!;
      const updated = { ...evt, read_at: new Date().toISOString() };
      return { ok: true, status: 200, json: async () => updated };
    }
    if (u.includes("/alerts")) {
      return { ok: true, status: 200, json: async () => events };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("AlertsFeed", () => {
  it("renders all events, then filters to restock only when the Restock chip is tapped", async () => {
    const events = sampleEvents();
    stubFetch(events);

    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={noop} />,
    );

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Charizard is back in stock");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Charizard hit your target");
    expect(text).toContain("Pokemon Center drop soon");

    const chips = [...container.querySelectorAll(".alert-chip")] as HTMLButtonElement[];
    const restockChip = chips.find((c) => /restock/i.test(c.textContent ?? ""))!;
    fireEvent.click(restockChip);

    const filtered = container.textContent ?? "";
    expect(filtered).toContain("Charizard is back in stock");
    expect(filtered).not.toContain("Charizard hit your target");
    expect(filtered).not.toContain("Pokemon Center drop soon");
  });

  it("renders unread rows visually distinct and marks one read when tapped (PATCH /alerts/{id})", async () => {
    const events = sampleEvents();
    const spy = stubFetch(events);

    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={noop} />,
    );

    await waitFor(() => {
      expect(container.querySelector(".alert-row")).not.toBeNull();
    });

    const rows = container.querySelectorAll(".alert-row");
    // The first and third events are unread (read_at null); the second is read.
    expect(rows[0].classList.contains("unread")).toBe(true);
    expect(rows[1].classList.contains("unread")).toBe(false);

    // Tapping the unread restock row fires a PATCH /alerts/1.
    fireEvent.click(rows[0]);

    await waitFor(() => {
      const patchCalls = spy.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCalls.length).toBeGreaterThanOrEqual(1);
      expect(String(patchCalls[0][0])).toMatch(/\/alerts\/1$/);
    });
  });

  it("honest empty state: shows the radar copy + 'Watch a card' CTA and never fabricates an event", async () => {
    stubFetch([]);

    const openSheet = vi.fn();
    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={openSheet} />,
    );

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/radar/i);
    });
    const text = container.textContent ?? "";
    expect(text).toMatch(/watch a card to get pinged/i);

    // No fabricated event row.
    expect(container.querySelector(".alert-row")).toBeNull();

    const cta = [...container.querySelectorAll("button")].find((b) =>
      /watch a card/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(cta).toBeDefined();
    fireEvent.click(cta);
    expect(openSheet).toHaveBeenCalledTimes(1);
  });

  it("opens a card detail when a row with a card_id is tapped", async () => {
    const events = sampleEvents();
    stubFetch(events);

    const openCard = vi.fn();
    const { container } = render(
      <AlertsFeed onOpenCard={openCard} onWatchCard={noop} />,
    );

    await waitFor(() => {
      expect(container.querySelector(".alert-row")).not.toBeNull();
    });

    const rows = container.querySelectorAll(".alert-row");
    // The first row has card_id base1-4 → should open the card detail.
    fireEvent.click(rows[0]);

    await waitFor(() => {
      expect(openCard).toHaveBeenCalledWith({ cardId: "base1-4", variant: undefined });
    });
  });
});