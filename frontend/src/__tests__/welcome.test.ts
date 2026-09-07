import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  WELCOME_SEEN_KEY,
  FIRST_SCAN_DONE_KEY,
  clearWelcomeSeen,
  readWelcomeSeen,
  writeWelcomeSeen,
  readFirstScanDone,
  writeFirstScanDone,
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

// The first-scan gate is a *separate* flag from the welcome overlay: it retires
// the "point at a card" hint caption and the one-time "Added to your Vault" toast
// once the scan→add loop has actually been completed once. Same try/catch guard.
describe("first-scan gate", () => {
  it("is not done by default on a fresh device", () => {
    expect(readFirstScanDone()).toBe(false);
  });

  it("records a first scan so the hint and toast retire", () => {
    writeFirstScanDone();
    expect(localStorage.getItem(FIRST_SCAN_DONE_KEY)).toBe("1");
    expect(readFirstScanDone()).toBe(true);
  });

  it("never throws when localStorage access fails", () => {
    const spies = [
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("blocked");
      }),
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("blocked");
      }),
    ];
    try {
      expect(readFirstScanDone()).toBe(false);
      expect(() => writeFirstScanDone()).not.toThrow();
    } finally {
      spies.forEach((s) => s.mockRestore());
    }
  });
});