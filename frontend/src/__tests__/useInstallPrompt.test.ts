import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useInstallPrompt } from "../lib/useInstallPrompt";

// The hook wraps three browser signals (beforeinstallprompt, appinstalled,
// display-mode: standalone / iOS standalone). jsdom fires none of them and
// reports a desktop UA, so the default state is "not installable, not iOS" —
// these tests drive each branch by dispatching the real events and stubbing
// the UA for the iOS branch.

afterEach(() => vi.unstubAllGlobals());

// A beforeinstallprompt event carries two non-standard members the DOM Event
// type doesn't model — prompt() and userChoice — so attach them to a plain
// Event the way Chromium does.
function bipEvent(opts: { choice: "accepted" | "dismissed"; promptFn?: () => Promise<void> }) {
  const evt = new Event("beforeinstallprompt");
  Object.assign(evt, {
    prompt: opts.promptFn ?? vi.fn(async () => {}),
    userChoice: Promise.resolve(opts.choice),
  });
  return evt as Event & { prompt: () => Promise<void>; userChoice: Promise<"accepted" | "dismissed"> };
}

describe("useInstallPrompt", () => {
  it("starts not-installable in jsdom (no event, desktop UA)", () => {
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.canInstall).toBe(false);
    expect(result.current.iosInstructions).toBe(false);
    expect(result.current.installed).toBe(false);
  });

  it("captures beforeinstallprompt and reports canInstall", () => {
    const { result } = renderHook(() => useInstallPrompt());
    act(() => {
      window.dispatchEvent(bipEvent({ choice: "accepted" }));
    });
    expect(result.current.canInstall).toBe(true);
  });

  it("promptInstall calls .prompt() and returns the user's choice, then clears", async () => {
    const promptFn = vi.fn(async () => {});
    const { result } = renderHook(() => useInstallPrompt());
    act(() => {
      window.dispatchEvent(bipEvent({ choice: "accepted", promptFn }));
    });
    let outcome = "unavailable" as string;
    await act(async () => {
      outcome = await result.current.promptInstall();
    });
    expect(promptFn).toHaveBeenCalledTimes(1);
    expect(outcome).toBe("accepted");
    expect(result.current.canInstall).toBe(false);
  });

  it("returns unavailable when no prompt is captured", async () => {
    const { result } = renderHook(() => useInstallPrompt());
    let outcome = "accepted" as string;
    await act(async () => {
      outcome = await result.current.promptInstall();
    });
    expect(outcome).toBe("unavailable");
  });

  it("appinstalled clears the captured prompt", () => {
    const { result } = renderHook(() => useInstallPrompt());
    act(() => {
      window.dispatchEvent(bipEvent({ choice: "dismissed" }));
    });
    expect(result.current.canInstall).toBe(true);
    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });
    expect(result.current.canInstall).toBe(false);
  });

  it("surfaces iOS Share-sheet instructions when the UA is iOS and no prompt fires", () => {
    // iOS Safari never fires beforeinstallprompt — the only honest install
    // surface is the Share → Add to Home Sheet menu, so the hook flags it.
    const original = navigator.userAgent;
    Object.defineProperty(navigator, "userAgent", {
      configurable: true,
      value: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    });
    try {
      const { result } = renderHook(() => useInstallPrompt());
      expect(result.current.iosInstructions).toBe(true);
      expect(result.current.canInstall).toBe(false);
    } finally {
      Object.defineProperty(navigator, "userAgent", { configurable: true, value: original });
    }
  });
});