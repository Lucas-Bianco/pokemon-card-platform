import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import SetDetail from "../components/SetDetail";

const noop = () => {};

function stubDetail(body: Record<string, unknown>) {
  const spy = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes("/sets/")) return { ok: true, status: 200, json: async () => body };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

const detail = {
  id: "base1", name: "Base", series: "Base", release_date: "1999/01/09",
  total: 3, printed_total: 3,
  cards: [
    { card_id: "base1-1", name: "Bulbasaur", number: "1", rarity: "Common",
      image_small: null, owned: true, market: null, source: null, source_updated_at: null },
    { card_id: "base1-2", name: "Ivysaur", number: "2", rarity: "Uncommon",
      image_small: null, owned: false, market: 3.0, source: "tcgplayer", source_updated_at: "2026/07/28" },
    { card_id: "base1-3", name: "Venusaur", number: "3", rarity: "Rare",
      image_small: null, owned: false, market: null, source: null, source_updated_at: null },
  ],
  summary: { owned: 1, checklist_size: 3, missing: 2, pct_complete: 1 / 3,
    est_cost_to_complete: 3.0, unpriced_missing: 1 },
};

describe("SetDetail", () => {
  it("renders the summary KPIs and the checklist ordered by number", async () => {
    stubDetail(detail);
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);

    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const text = container.textContent ?? "";
    expect(text).toContain("1 / 3 owned");
    expect(text).toContain("33%"); // Math.round(1/3 * 100) = 33
    expect(text).toContain("$3.00"); // est cost to complete
    expect(text).toContain("unpriced: 1");
    // ordered by number
    const nums = [...container.querySelectorAll(".checklist-num")].map((e) => e.textContent);
    expect(nums).toEqual(["1", "2", "3"]);
  });

  it("marks owned cards with an Owned badge and missing cards with a price or 'no market price'", async () => {
    stubDetail(detail);
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const tiles = container.querySelectorAll(".checklist-tile");
    expect(tiles[0].textContent).toMatch(/owned/i);
    expect(tiles[1].textContent).toContain("$3.00");
    expect(tiles[1].textContent).toContain("tcgplayer");
    expect(tiles[2].textContent).toMatch(/no market price/i);
  });

  it("shows 'Complete' and no $0.00 when the set is fully owned", async () => {
    stubDetail({
      ...detail,
      cards: detail.cards.map((c) => ({ ...c, owned: true })),
      summary: { owned: 3, checklist_size: 3, missing: 0, pct_complete: 1,
        est_cost_to_complete: 0.0, unpriced_missing: 0 },
    });
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/complete/i);
    });
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("shows an em dash for est cost when all missing are unpriced", async () => {
    stubDetail({
      ...detail,
      summary: { owned: 0, checklist_size: 3, missing: 3, pct_complete: 0,
        est_cost_to_complete: null, unpriced_missing: 3 },
    });
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.querySelector(".set-detail-cost")?.textContent).toContain("—");
    });
  });

  it("clicking a checklist tile calls onSelectCard with the card id", async () => {
    const spy = stubDetail(detail);
    void spy;
    const onSelectCard = vi.fn();
    const { container } = render(<SetDetail setId="base1" onBack={noop} onSelectCard={onSelectCard} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    fireEvent.click(container.querySelectorAll(".checklist-tile")[1]);
    expect(onSelectCard).toHaveBeenCalledWith("base1-2");
  });

  it("renders a back button that calls onBack", async () => {
    stubDetail(detail);
    const onBack = vi.fn();
    const { container } = render(<SetDetail setId="base1" onBack={onBack} onSelectCard={noop} />);
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Base");
    });
    const back = [...container.querySelectorAll("button")].find((b) =>
      /back/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});