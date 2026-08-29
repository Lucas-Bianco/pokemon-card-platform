// Two faces of the same app, toggled from the More tab:
//   - "key"  — the curated flagship: the six core collector-loop features
//              (Scan, Vault, Binder, Sets, Sealed, Deals) front and centre in
//              the nav, every other surface tucked under More. This is the
//              default, because it is the version the project invests in
//              refining to its best form.
//   - "full" — the existing app unchanged: all 15 tabs in the nav.
//
// The choice is a single localStorage string so it survives reloads and is
// available synchronously at first render (no flash of the wrong nav). The
// read/write helpers guard localStorage access so a disabled/quota-exceeded
// store degrades to the default rather than throwing the app out.

export type AppMode = "key" | "full";

export const APP_MODE_STORAGE_KEY = "cardplatform_app_mode";

export const DEFAULT_APP_MODE: AppMode = "key";

export function readAppMode(): AppMode {
  try {
    return localStorage.getItem(APP_MODE_STORAGE_KEY) === "full" ? "full" : "key";
  } catch {
    return DEFAULT_APP_MODE;
  }
}

export function writeAppMode(mode: AppMode): void {
  try {
    localStorage.setItem(APP_MODE_STORAGE_KEY, mode);
  } catch {
    /* localStorage unavailable or full — the in-memory state still drives the UI. */
  }
}