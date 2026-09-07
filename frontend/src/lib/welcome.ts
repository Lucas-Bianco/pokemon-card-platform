// First-run welcome-overlay gate. A single localStorage flag so the onboarding
// overlay (the scan → value → vault/binder loop) shows exactly once per device,
// and can be re-shown from the More tab. Mirrors lib/appMode.ts: the read/write
// helpers guard localStorage access so a disabled or quota-exceeded store
// degrades to "show once" / "no-op" rather than throwing the app out.

export const WELCOME_SEEN_KEY = "cardplatform_welcome_seen";

// Has the user already dismissed the welcome overlay? false = show it (the
// default for a brand-new device), true = already seen, don't show again.
export function readWelcomeSeen(): boolean {
  try {
    return localStorage.getItem(WELCOME_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeWelcomeSeen(): void {
  try {
    localStorage.setItem(WELCOME_SEEN_KEY, "1");
  } catch {
    /* localStorage unavailable or full — the in-memory dismiss still hides it. */
  }
}

// Re-show on next mount (used by More's "Show welcome again" link). The overlay
// reads the flag at mount, so this takes effect the next time the app boots or
// the Scan view mounts — not instantaneously, deliberately low-risk.
export function clearWelcomeSeen(): void {
  try {
    localStorage.removeItem(WELCOME_SEEN_KEY);
  } catch {
    /* a disabled store can't have remembered the flag anyway. */
  }
}