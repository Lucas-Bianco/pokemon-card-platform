import { describe, expect, it } from "vitest";

import { formatMoney, formatStaleness, statusLabel } from "../lib/format";

describe("formatMoney", () => {
  it("formats a price", () => {
    expect(formatMoney(800.43)).toBe("$800.43");
  });

  it("renders an absent price as a dash rather than $0", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });

  it("keeps two decimals on whole numbers", () => {
    expect(formatMoney(12)).toBe("$12.00");
  });

  it("does not treat a genuine zero as missing", () => {
    expect(formatMoney(0)).toBe("$0.00");
  });
});

describe("formatStaleness", () => {
  it("passes through a source date", () => {
    expect(formatStaleness("2026/07/29")).toBe("as of 2026/07/29");
  });

  it("says so when the source gave no date", () => {
    expect(formatStaleness("")).toBe("date unknown");
    expect(formatStaleness(null)).toBe("date unknown");
  });
});

describe("statusLabel", () => {
  it("maps each recognition status to human wording", () => {
    expect(statusLabel("confident")).toBe("Identified");
    expect(statusLabel("ambiguous")).toBe("Not sure — pick one");
    expect(statusLabel("not_found")).toBe("No card found");
  });
});
