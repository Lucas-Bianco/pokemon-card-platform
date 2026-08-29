import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import More from "../components/More";
import type { AppMode } from "../lib/appMode";

// More now takes the app mode + setter (the App mode toggle lives at the top of
// the pane). These push-channel tests don't exercise the toggle, so they pass a
// no-op setter and the default 'key' mode — the channel cards render identically
// regardless of mode.
function renderMore(mode: AppMode = "key") {
  return render(<More appMode={mode} onAppModeChange={() => {}} />);
}

// A minimal fake of the browser Push API. jsdom ships neither serviceWorker nor
// PushManager, so the whole surface the component touches is stubbed here: the
// registration's pushManager, the subscription, and its unsubscribe().
function stubPush(opts: { subscribed: boolean; unsubscribeResult?: boolean }) {
  const unsubscribe = vi.fn(async () => opts.unsubscribeResult ?? true);
  const subscription = {
    endpoint: "https://push.example/abc",
    unsubscribe,
    getKey: () => null,
  };
  const getSubscription = vi.fn(async () => (opts.subscribed ? subscription : null));
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve({ pushManager: { getSubscription } }) },
  });
  return { unsubscribe, getSubscription, subscription };
}

// Routed fetch stub: the watchlist section mounts alongside the channel cards,
// so GET /watches must answer or the pane never settles.
function stubFetch(deleteStatus = 204) {
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes("/push/subscribe") && init?.method === "DELETE") {
      return { ok: deleteStatus < 400, status: deleteStatus, json: async () => ({}) };
    }
    if (u.includes("/watchlist")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function clickDisable(container: HTMLElement) {
  const button = [...container.querySelectorAll("button")].find(
    (b) => (b.textContent ?? "").trim() === "Disable push",
  );
  expect(button).toBeDefined();
  fireEvent.click(button as HTMLElement);
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("More - push can be turned off", () => {
  it("reflects an existing browser subscription instead of claiming Off", async () => {
    stubPush({ subscribed: true });
    stubFetch();

    const { container } = renderMore();

    await waitFor(() => {
      expect(container.querySelector(".channel-on")).not.toBeNull();
    });
    expect(container.textContent ?? "").toContain("Disable push");
  });

  it("offers no disable action when nothing is subscribed", async () => {
    stubPush({ subscribed: false });
    stubFetch();

    const { container } = renderMore();

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Enable push");
    });
    expect(container.textContent ?? "").not.toContain("Disable push");
  });

  it("unsubscribes the browser AND deletes the server record", async () => {
    const { unsubscribe } = stubPush({ subscribed: true });
    const spy = stubFetch();

    const { container } = renderMore();
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Disable push");
    });

    clickDisable(container);

    await waitFor(() => {
      expect(unsubscribe).toHaveBeenCalledTimes(1);
    });
    const del = spy.mock.calls.find(
      ([u, init]) =>
        String(u).includes("/push/subscribe") && (init as RequestInit)?.method === "DELETE",
    );
    expect(del).toBeDefined();
    expect(String(del![0])).toContain(encodeURIComponent("https://push.example/abc"));

    // And the card goes back to Off, offering Enable again.
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Enable push");
    });
    expect(container.querySelector(".channel-off")).not.toBeNull();
  });

  it("treats an already-deleted server record (404) as successfully off", async () => {
    const { unsubscribe } = stubPush({ subscribed: true });
    stubFetch(404);

    const { container } = renderMore();
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Disable push");
    });
    clickDisable(container);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Enable push");
    });
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    // The browser subscription is gone, so push IS off - never an error.
    expect(container.querySelector(".error")).toBeNull();
  });

  it("reports honestly when the browser refuses to unsubscribe", async () => {
    stubPush({ subscribed: true, unsubscribeResult: false });
    stubFetch();

    const { container } = renderMore();
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Disable push");
    });
    clickDisable(container);

    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/couldn't turn push off/i);
    });
  });
});
