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
    {
      id: 4,
      watch_id: 13,
      card_id: "base1-4",
      alert_type: "deal",
      message: "Charizard listing cleared the RIP/flip deal thresholds",
      context: null,
      delivered_push: false,
      delivered_email: false,
      read_at: null,
      created_at: new Date(now - 5 * 60 * 1000).toISOString(),
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

// A fetch stub whose POST /alerts/check returns a pinned pull result. The
// catchall GET /alerts returns the supplied feed so the empty-state pull can
// still render. Used by the row-20 pull tests.
function stubFetchWithCheck(events: AlertEvent[], check: { fired: number; events: AlertEvent[] }) {
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/alerts/unread-count")) {
      return { ok: true, status: 200, json: async () => ({ count: 0 }) };
    }
    if (u.includes("/alerts/check") && method === "POST") {
      return { ok: true, status: 200, json: async () => check };
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

  it("filters to deal alerts when the Deals chip is tapped", async () => {
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
    expect(text).toContain("Charizard listing cleared the RIP/flip deal thresholds");

    const chips = [...container.querySelectorAll(".alert-chip")] as HTMLButtonElement[];
    const dealsChip = chips.find((c) => /deals/i.test(c.textContent ?? ""))!;
    fireEvent.click(dealsChip);

    const filtered = container.textContent ?? "";
    expect(filtered).toContain("Charizard listing cleared the RIP/flip deal thresholds");
    expect(filtered).not.toContain("Charizard is back in stock");
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

  // ----- Row 20: the on-demand pull (Check now) ---------------------------

  it("Check now prepends freshly-fired events and shows an honest 'N new' note", async () => {
    const events = sampleEvents();
    const fresh: AlertEvent = {
      id: 99,
      watch_id: 20,
      card_id: "base1-4",
      alert_type: "price_target",
      message: "Charizard hit your target",
      context: null,
      delivered_push: false,
      delivered_email: false,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    const spy = stubFetchWithCheck(events, { fired: 1, events: [fresh] });

    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={noop} />,
    );
    await waitFor(() => {
      expect(container.querySelector(".alert-row")).not.toBeNull();
    });

    const checkBtn = [...container.querySelectorAll("button")].find((b) =>
      /check now/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(checkBtn).toBeDefined();
    fireEvent.click(checkBtn);

    // A POST /alerts/check fired.
    await waitFor(() => {
      const checkCalls = spy.mock.calls.filter(
        ([u, init]) =>
          String(u).includes("/alerts/check") &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(checkCalls.length).toBeGreaterThanOrEqual(1);
    });

    // The fresh row is prepended at the top, and the honest note names the count.
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Checked — 1 new alert.");
    });
    const rows = container.querySelectorAll(".alert-row");
    expect(rows[0].textContent ?? "").toContain("Charizard hit your target");
  });

  it("Check now with 0 fired shows the honest 'nothing new yet' note and fabricates no event", async () => {
    stubFetchWithCheck([], { fired: 0, events: [] });

    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={noop} />,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/radar/i);
    });

    // Empty state still surfaces the Check now pull.
    const checkBtn = [...container.querySelectorAll("button")].find((b) =>
      /check now/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(checkBtn).toBeDefined();
    fireEvent.click(checkBtn);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("nothing new yet");
    });
    // The pull-model contract copy is present.
    expect(container.textContent ?? "").toMatch(/pull, not push/i);
    // No fabricated event row.
    expect(container.querySelector(".alert-row")).toBeNull();
  });

  it("Check now surfaces an honest error note when the pull fails (never a fabricated event)", async () => {
    const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? "GET";
      if (u.includes("/alerts/unread-count")) {
        return { ok: true, status: 200, json: async () => ({ count: 0 }) };
      }
      if (u.includes("/alerts/check") && method === "POST") {
        return { ok: false, status: 500, json: async () => ({}) };
      }
      if (u.includes("/alerts")) {
        return { ok: true, status: 200, json: async () => [] };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", spy);

    const { container } = render(
      <AlertsFeed onOpenCard={noop} onWatchCard={noop} />,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/radar/i);
    });

    const checkBtn = [...container.querySelectorAll("button")].find((b) =>
      /check now/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(checkBtn);

    await waitFor(() => {
      // The honest error message surfaces verbatim, not a fabricated friendly
      // fallback — the user sees the real failure.
      expect(container.textContent ?? "").toContain("request failed: 500");
    });
    expect(container.querySelector(".alert-row")).toBeNull();
  });
});