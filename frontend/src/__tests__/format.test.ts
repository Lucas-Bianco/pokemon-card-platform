import { describe, expect, it } from "vitest";

import { formatMoney, formatStaleness, sourceLabel, statusLabel } from "../lib/format";

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

describe("sourceLabel", () => {
  it("translates the TCGplayer slug (and its via-variants) to a market-reference label", () => {
    expect(sourceLabel("tcgplayer")).toBe("TCGplayer market reference");
    expect(sourceLabel("tcgplayer_via_ptcgo")).toBe("TCGplayer market reference");
    expect(sourceLabel("tcgplayer_via_pokemontcg")).toBe("TCGplayer market reference");
  });

  it("translates the Cardmarket fallback to an aggregate label", () => {
    expect(sourceLabel("cardmarket")).toBe("Cardmarket aggregate");
  });

  it("translates eBay sold-comps sources", () => {
    expect(sourceLabel("ebay_sold")).toBe("eBay sold comps");
    expect(sourceLabel("ebay")).toBe("eBay sold comps");
  });

  it("matches case-insensitively so backend casing drift doesn't leak a raw slug", () => {
    expect(sourceLabel("TCGPlayer")).toBe("TCGplayer market reference");
    expect(sourceLabel("CardMarket")).toBe("Cardmarket aggregate");
  });

  it("leaves an unrecognized slug unchanged (a proper name, not coerced)", () => {
    expect(sourceLabel("pkmnprices")).toBe("pkmnprices");
  });

  it("says 'source unknown' for null/empty so a price is never next to a blank", () => {
    expect(sourceLabel(null)).toBe("source unknown");
    expect(sourceLabel("")).toBe("source unknown");
    expect(sourceLabel("   ")).toBe("source unknown");
    expect(sourceLabel(undefined)).toBe("source unknown");
  });
});
