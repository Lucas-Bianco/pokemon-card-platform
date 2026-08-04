import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import WatchCardSheet from "../components/WatchCardSheet";

const noop = () => {};

// fetch stub routed by URL + method. POST /watchlist returns the created
// watch (201) by default, or a 422 with {detail} when `rejectWith` is set.
// GET /cards?name= returns card-search results for the no-cardId search path.
function stubFetch(options: {
  rejectWith?: { status: number; detail: string };
  watch?: Record<string, unknown>;
  cards?: Array<Record<string, unknown>>;
} = {}) {
  const opts = {
    watch: {
      id: 99,
      card_id: "base1-4",
      subject_label: null,
      variant: null,
      alert_type: "price_target",
      target_price: 40.0,
      drop_at: null,
      lead_time_min: null,
      auction_window_min: null,
      active: true,
      last_fired_at: null,
      created_at: "2026-08-01T00:00:00Z",
    },
    cards: [],
    ...options,
  };
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/watchlist") && method === "POST") {
      if (opts.rejectWith) {
        return {
          ok: false,
          status: opts.rejectWith.status,
          json: async () => ({ detail: opts.rejectWith!.detail }),
        };
      }
      return { ok: true, status: 201, json: async () => opts.watch };
    }
    if (u.includes("/cards?") || u.includes("/cards&")) {
      return { ok: true, status: 200, json: async () => opts.cards };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("WatchCardSheet", () => {
  it("Price target: shows the target input; submitting target=40 POSTs the right payload", async () => {
    const spy = stubFetch();
    const onCreated = vi.fn();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={onCreated} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const priceChip = chips.find((c) => /price target/i.test(c.textContent ?? ""))!;
    fireEvent.click(priceChip);

    const targetInput = container.querySelector(
      'input[name="target_price"]',
    ) as HTMLInputElement;
    expect(targetInput).not.toBeNull();
    fireEvent.change(targetInput, { target: { value: "40" } });

    const submit = [...container.querySelectorAll("button")].find((b) =>
      /^watch$/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(spy.mock.calls.some(([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST")).toBe(true);
    });
    const postCall = spy.mock.calls.find(
      ([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST",
    )!;
    const body = JSON.parse((postCall[1] as RequestInit).body as string);
    expect(body.alert_type).toBe("price_target");
    expect(body.target_price).toBe(40);
    expect(body.card_id).toBe("base1-4");
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it("Drop time: shows datetime + lead inputs + the 'works without a listings source' note; submits drop_at + lead_time_min", async () => {
    const spy = stubFetch();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={noop} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const dropChip = chips.find((c) => /drop time/i.test(c.textContent ?? ""))!;
    fireEvent.click(dropChip);

    const dropInput = container.querySelector(
      'input[name="drop_at"]',
    ) as HTMLInputElement;
    expect(dropInput).not.toBeNull();
    const leadInput = container.querySelector(
      'input[name="lead_time_min"]',
    ) as HTMLInputElement;
    expect(leadInput).not.toBeNull();

    expect(container.textContent ?? "").toMatch(/works without a listings source/i);

    fireEvent.change(dropInput, { target: { value: "2026-08-15T18:00" } });
    fireEvent.change(leadInput, { target: { value: "60" } });

    const submit = [...container.querySelectorAll("button")].find((b) =>
      /^watch$/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(spy.mock.calls.some(([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST")).toBe(true);
    });
    const postCall = spy.mock.calls.find(
      ([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST",
    )!;
    const body = JSON.parse((postCall[1] as RequestInit).body as string);
    expect(body.alert_type).toBe("drop_time");
    expect(body.drop_at).toBe("2026-08-15T18:00");
    expect(body.lead_time_min).toBe(60);
  });

  it("Auction ending: shows the window input defaulting to 30", async () => {
    stubFetch();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={noop} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const auctionChip = chips.find((c) => /auction ending/i.test(c.textContent ?? ""))!;
    fireEvent.click(auctionChip);

    const windowInput = container.querySelector(
      'input[name="auction_window_min"]',
    ) as HTMLInputElement;
    expect(windowInput).not.toBeNull();
    expect(windowInput.value).toBe("30");
  });

  it("surfaces the backend's 422 detail message as an honest error", async () => {
    stubFetch({ rejectWith: { status: 422, detail: "target_price is required for alert_type 'price_target'" } });
    const onCreated = vi.fn();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={onCreated} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const priceChip = chips.find((c) => /price target/i.test(c.textContent ?? ""))!;
    fireEvent.click(priceChip);

    const targetInput = container.querySelector(
      'input[name="target_price"]',
    ) as HTMLInputElement;
    fireEvent.change(targetInput, { target: { value: "40" } });

    const submit = [...container.querySelectorAll("button")].find((b) =>
      /^watch$/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("target_price is required for alert_type 'price_target'");
    });
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("Deal: picking the Deal chip submits a deal watch with alert_type=deal", async () => {
    const spy = stubFetch();
    const onCreated = vi.fn();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={onCreated} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const dealChip = chips.find((c) => /deal/i.test(c.textContent ?? ""))!;
    fireEvent.click(dealChip);

    const submit = [...container.querySelectorAll("button")].find((b) =>
      /^watch$/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(spy.mock.calls.some(([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST")).toBe(true);
    });
    const postCall = spy.mock.calls.find(
      ([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST",
    )!;
    const body = JSON.parse((postCall[1] as RequestInit).body as string);
    expect(body.alert_type).toBe("deal");
    expect(body.card_id).toBe("base1-4");
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it("Restock: shows the 'requires a listings source key' honest note", async () => {
    stubFetch();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={noop} />,
    );

    // Restock is the default type, but assert the note is present.
    expect(container.textContent ?? "").toMatch(/requires a listings source/i);
  });

  it("client-side validates: price target without a target shows a helpful message and does not POST", async () => {
    const spy = stubFetch();

    const { container } = render(
      <WatchCardSheet cardId="base1-4" onClose={noop} onCreated={noop} />,
    );

    const chips = [...container.querySelectorAll(".watch-type-chip")] as HTMLButtonElement[];
    const priceChip = chips.find((c) => /price target/i.test(c.textContent ?? ""))!;
    fireEvent.click(priceChip);

    // Leave the target empty and submit.
    const submit = [...container.querySelectorAll("button")].find((b) =>
      /^watch$/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/target price is required/i);
    });
    expect(
      spy.mock.calls.some(([u, i]) => String(u).includes("/watchlist") && (i as RequestInit)?.method === "POST"),
    ).toBe(false);
  });
});