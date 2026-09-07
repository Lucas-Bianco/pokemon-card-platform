import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  WELCOME_SEEN_KEY,
  clearWelcomeSeen,
  readWelcomeSeen,
  writeWelcomeSeen,
} from "../lib/welcome";

// The welcome-overlay gate is a localStorage flag. vitest.setup clears
// localStorage before each test, so each starts from the "not seen" default.
beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* jsdom always has localStorage. */
  }
});

describe("welcome gate", () => {
  it("is not seen by default on a fresh device", () => {
    expect(readWelcomeSeen()).toBe(false);
  });

  it("records a dismiss so it does not show again", () => {
    writeWelcomeSeen();
    expect(localStorage.getItem(WELCOME_SEEN_KEY)).toBe("1");
    expect(readWelcomeSeen()).toBe(true);
  });

  it("can be cleared so the overlay re-shows on next mount", () => {
    writeWelcomeSeen();
    expect(readWelcomeSeen()).toBe(true);

    clearWelcomeSeen();
    expect(localStorage.getItem(WELCOME_SEEN_KEY)).toBeNull();
    expect(readWelcomeSeen()).toBe(false);
  });

  it("never throws when localStorage access fails", () => {
    // jsdom's localStorage is a read-only getter, so stub the Storage prototype
    // methods the helpers touch to throw — exercising every try/catch guard.
    const spies = [
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("blocked");
      }),
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("blocked");
      }),
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new Error("blocked");
      }),
    ];
    try {
      expect(readWelcomeSeen()).toBe(false);
      expect(() => writeWelcomeSeen()).not.toThrow();
      expect(() => clearWelcomeSeen()).not.toThrow();
    } finally {
      spies.forEach((s) => s.mockRestore());
    }
  });
});