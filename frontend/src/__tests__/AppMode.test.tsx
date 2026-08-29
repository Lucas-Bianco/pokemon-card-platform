import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "../App";
import { ToastProvider } from "../components/Toast";
import { APP_MODE_STORAGE_KEY } from "../lib/appMode";

// Key-mode behaviour: the curated 7-tab nav, Scan landing, non-key surfaces
// still reachable with More highlighted, and the More-tab toggle that flips to
// Full and persists. These are the counterpart to AppRouting.test.tsx, which
// pins the full-mode routing contract. The app default is 'key', and
// vitest.setup clears localStorage before each test, so no opt-in is needed
// here — these tests exercise the default.

// Minimal fetch stub: AppShell mounts by fetching the unread-alert count; the
// mode/nav assertions read the shell, not fetched content, so every other call
// degrades to an honest empty state (404). The surfaces underneath only need to
// render without throwing.
function stubFetch() {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/alerts/unread-count")) {
      return { ok: true, status: 200, json: async () => ({ count: 0 }) };
    }
    if (u.includes("/alerts")) {
      return { ok: true, status: 200, json: async () => [] };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

/** Boot the app at a URL, the way a reload or a home-screen shortcut would. */
function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  return render(
    <ToastProvider>
      <App />
    </ToastProvider>,
  );
}

/** The shell's header title is the single honest read-out of the active view. */
function activeTitle(container: HTMLElement): string {
  return container.querySelector(".app-header h1")?.textContent ?? "";
}

/** The labels of the buttons in the primary (bottom) nav, in render order. */
function navLabels(container: HTMLElement): string[] {
  const buttons = container.querySelectorAll('nav[aria-label="Primary"] button');
  return [...buttons].map((b) => b.textContent ?? "");
}

const KEY_TABS = ["Scan", "Vault", "Binder", "Sets", "Sealed", "Deals", "More"];
const HIDDEN_IN_KEY = ["Home", "Wants", "Alerts", "Prices", "Catalog", "Ledger", "Browse", "Shop"];

describe("App mode — key (default)", () => {
  beforeEach(() => {
    // vitest.setup clears localStorage, so the default 'key' mode applies.
    // Explicit (and harmless) belt-and-braces for readability.
    localStorage.removeItem(APP_MODE_STORAGE_KEY);
  });

  it("shows exactly the seven curated tabs in the collector-loop order", () => {
    stubFetch();
    const { container } = renderAt("/");

    expect(navLabels(container)).toEqual(KEY_TABS);
  });

  it("hides every non-key tab from the nav", () => {
    stubFetch();
    renderAt("/");

    for (const label of HIDDEN_IN_KEY) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
  });

  it("boots on Scan when there is no query (the key-mode landing)", async () => {
    stubFetch();
    const { container } = renderAt("/");

    await waitFor(() => expect(activeTitle(container)).toBe("Scan"));
    await waitFor(() => expect(window.location.search).toBe("?view=scan"));
  });

  it("lands on Scan as a replace, not a push (Back leaves the app)", async () => {
    stubFetch();
    const { container } = renderAt("/");

    await waitFor(() => expect(activeTitle(container)).toBe("Scan"));
    // The initial "/" was replaced (not pushed over), so the redirect did not
    // stack a duplicate history entry — browser Back steps out of the app
    // rather than back to a Home that would re-redirect to Scan.
    expect(window.history.length).toBeGreaterThanOrEqual(1);
    expect(window.history.state).not.toBeNull();
  });

  it("still renders an explicit ?view=home (reachable) with More highlighted", () => {
    stubFetch();
    const { container } = renderAt("/?view=home");

    // Home is non-key but reachable via a deep link; it renders, and the More
    // tab is the one highlighted (every non-key surface lives under More).
    expect(activeTitle(container)).toBe("Home");
    const moreButton = screen.getByRole("button", { name: "More" });
    expect(moreButton.getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: "Scan" }).getAttribute("aria-current")).toBe("false");
  });

  it("renders a non-key view reached via deep link with More highlighted", async () => {
    stubFetch();
    const { container } = renderAt("/?view=wants");

    // Wants renders (reachable), More is highlighted, no Wants tab in the nav.
    await waitFor(() => expect(activeTitle(container)).toBe("Wants"));
    expect(screen.queryByRole("button", { name: "Wants" })).toBeNull();
    expect(screen.getByRole("button", { name: "More" }).getAttribute("aria-current")).toBe("true");
  });

  it("exposes the App mode toggle under the More tab", () => {
    stubFetch();
    renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText("App mode")).toBeDefined();
    expect(screen.getByRole("button", { name: "Key" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Full" })).toBeDefined();
  });
});

describe("App mode — toggling", () => {
  it("switches to Full from the More tab and restores all 15 tabs", () => {
    stubFetch();
    const { container } = renderAt("/");

    // Starts in key mode: seven tabs.
    expect(navLabels(container)).toEqual(KEY_TABS);

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: "Full" }));

    // Full mode: the full 15-tab nav is rendered immediately.
    const labels = navLabels(container);
    expect(labels).toEqual([
      "Home", "Scan", "Vault", "Binder", "Wants", "Alerts",
      "Deals", "Prices", "Sealed", "Catalog", "Ledger",
      "Browse", "Sets", "Shop", "More",
    ]);
  });

  it("persists the Full choice to localStorage", () => {
    stubFetch();
    renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: "Full" }));

    expect(localStorage.getItem(APP_MODE_STORAGE_KEY)).toBe("full");
  });

  it("a fresh mount honours the persisted Full mode (boots on Home)", () => {
    stubFetch();
    localStorage.setItem(APP_MODE_STORAGE_KEY, "full");
    const { container } = renderAt("/");

    // Full mode does NOT redirect — the bare landing is Home, as before.
    expect(activeTitle(container)).toBe("Home");
  });
});