import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Donut, MoverBars } from "../components/viz";
import type { Allocation, PortfolioItem } from "../api/types";

const alloc: Allocation[] = [
  { set_id: "a", set_name: "Base", market_value: 600, cost_basis: 400, item_count: 3 },
  { set_id: "b", set_name: "Jungle", market_value: 400, cost_basis: 300, item_count: 2 },
];
const gainers: PortfolioItem[] = [
  { id: 1, card_id: "a1", card_name: "Charizard", set_id: "a", set_name: "Base", variant: "normal", quantity: 1, acquired_price: 100, acquired_at: null, condition: null, notes: null, market_price: 250, market_source: "tcg", market_source_updated_at: null, unrealized: 150, priced: true },
];

describe("Donut", () => {
  it("renders the total when allocation exists", () => {
    const { container } = render(<Donut allocation={alloc} total={1000} />);
    expect(container.textContent).toContain("$1,000");
  });
  it("renders an honest em-dash when empty", () => {
    const { container } = render(<Donut allocation={[]} total={0} />);
    expect(container.querySelector("svg")?.getAttribute("aria-label")).toMatch(/no holdings/);
  });
});

describe("MoverBars", () => {
  it("renders a mover row", () => {
    const { container } = render(<MoverBars items={gainers} kind="gainers" />);
    expect(container.textContent).toContain("Charizard");
    expect(container.textContent).toContain("$150");
  });
  it("renders an honest empty note when no movers", () => {
    const { container } = render(<MoverBars items={[]} kind="losers" />);
    expect(container.textContent).toContain("No losers yet.");
  });
});