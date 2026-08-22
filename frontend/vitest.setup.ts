import { beforeEach } from "vitest";

// Navigation now lives in the URL, and jsdom keeps ONE window (and one session
// history) for every test in a file. Without this, a test that navigates to
// `?view=scan` would leave the next `render(<App/>)` in that file booting on the
// Scan tab instead of Home. Resetting the location per test keeps each one
// starting from the default landing view, exactly as they did before routing.
beforeEach(() => {
  window.history.replaceState(null, "", "/");
});
