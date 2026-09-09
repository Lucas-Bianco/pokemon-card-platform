import { useCallback, useEffect, useState } from "react";

// The browser fires BeforeInstallPromptEvent on Chromium (Android Chrome,
// Edge/Chrome desktop) when the PWA meets installability criteria, holding the
// prompt until you call `.prompt()` on the captured event. iOS Safari NEVER
// fires it — the only install path there is the Share → Add to Home Screen
// menu — so the UI must branch on iOS and show honest instructions instead of
// a dead "Install" button. This hook encapsulates all three states:
// `canInstall` (Chromium, prompt captured), `iosInstructions` (iOS, no prompt),
// and `installed` (already running standalone — nothing to do).

export type InstallOutcome = "accepted" | "dismissed" | "unavailable" | "error";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<"accepted" | "dismissed">;
}

// iOS Safari detection. Chrome on iOS (CriOS) still uses Apple's WKWebView and
// also lacks beforeinstallprompt, but the Share-sheet instructions are the same
// — so we only need "is this an iOS browser", not "is it Safari specifically".
function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  // iPadOS 13+ reports as MacIntel in Safari; the touchscreen check catches it.
  const ua = navigator.userAgent || "";
  if (/iPad|iPhone|iPod/.test(ua)) return true;
  const nav = navigator as Navigator & { maxTouchPoints?: number };
  if (ua.includes("MacIntel") && nav.maxTouchPoints && nav.maxTouchPoints > 1) {
    return true;
  }
  return false;
}

// True when the app is already running installed (standalone display mode, or
// iOS Safari's navigator.standalone). In that state there's nothing to install.
// navigator.standalone is an iOS-proprietary property not in the TS DOM lib, so
// read it through a Record index to avoid a property-access type error.
function isStandaloneDisplay(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) {
    return true;
  }
  return (navigator as unknown as Record<string, unknown>)["standalone"] === true;
}

export interface InstallPromptState {
  // Chromium captured the prompt — show an "Install app" button.
  canInstall: boolean;
  // iOS with no prompt — show Share → Add to Home Screen instructions.
  iosInstructions: boolean;
  // Already running as an installed app — no install surface needed.
  installed: boolean;
  // Trigger the captured prompt. Returns the user's choice, or "unavailable"
  // if no prompt is captured, or "error" if the browser rejects the call.
  promptInstall: () => Promise<InstallOutcome>;
}

export function useInstallPrompt(): InstallPromptState {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [ios] = useState(isIOS);
  const [standalone] = useState(isStandaloneDisplay);

  useEffect(() => {
    if (standalone) return; // installed: don't capture, the card won't render
    const onBeforeInstall = (e: Event) => {
      e.preventDefault(); // stop the browser's default mini-infobar
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setDeferred(null);
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, [standalone]);

  const promptInstall = useCallback(async (): Promise<InstallOutcome> => {
    if (!deferred) return "unavailable";
    try {
      await deferred.prompt();
      const choice = await deferred.userChoice;
      setDeferred(null);
      return choice;
    } catch {
      return "error";
    }
  }, [deferred]);

  return {
    canInstall: !!deferred,
    iosInstructions: !deferred && ios && !standalone,
    installed: standalone,
    promptInstall,
  };
}