import { beforeEach } from "vitest";

// Navigation now lives in the URL, and jsdom keeps ONE window (and one session
// history) for every test in a file. Without this, a test that navigates to
// `?view=scan` would leave the next `render(<App/>)` in that file booting on the
// Scan tab instead of Home. Resetting the location per test keeps each one
// starting from the default landing view, exactly as they did before routing.
beforeEach(() => {
  window.history.replaceState(null, "", "/");
  // The app mode (curated "key" vs all-tabs "full") is persisted to localStorage
  // and read at first render. Clear it per test so each one starts from the
  // default ('key') unless it explicitly opts into a mode — a test that toggled
  // to "full" must not leave the next test booting in full mode.
  try {
    localStorage.clear();
  } catch {
    /* jsdom always has localStorage; guard for type-safety only. */
  }
});
