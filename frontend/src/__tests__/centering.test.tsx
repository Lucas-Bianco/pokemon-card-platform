import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Centering, RecognizeResponse } from "../api/types";
import CenteringPanel from "../components/CenteringPanel";
import ScanResult from "../components/ScanResult";

function centering(overrides: Partial<Centering> = {}): Centering {
  return {
    left_right: [58.0, 42.0],
    top_bottom: [51.0, 49.0],
    worst_axis: 58.0,
    uncertainty: 2.5,
    psa_cap: 9,
    psa_cap_certain: true,
    ...overrides,
  };
}

describe("CenteringPanel", () => {
  it("renders both axis ratios and the worse axis", () => {
    const { container } = render(<CenteringPanel centering={centering()} />);
    const text = container.textContent ?? "";

    expect(text).toContain("58 / 42");
    expect(text).toContain("51 / 49");
    // The worse of the four shares, so the reader knows which number drives the cap.
    expect(text).toMatch(/worst axis/i);
    expect(text).toContain("58.0");
  });

  it("states a ceiling, never a verdict on the card", () => {
    const { container } = render(<CenteringPanel centering={centering()} />);
    const text = container.textContent ?? "";

    expect(text).toContain("allows up to PSA 9");
    // The whole point of the panel: centering can only rule a grade out.
    expect(text).not.toMatch(/this card is/i);
    expect(text).not.toMatch(/\bgrades? (?:a |an )?(?:PSA )?\d/i);
  });

  it("declines to separate neighbouring grades when the interval straddles a boundary", () => {
    const { container } = render(
      <CenteringPanel centering={centering({ psa_cap_certain: false })} />,
    );
    const text = container.textContent ?? "";

    expect(text).toMatch(/too close to call/i);
    expect(text).toContain("58.0");
    expect(text).toContain("2.5");
    expect(text).toMatch(/cannot separate/i);
  });

  it("says centering is out of range rather than inventing a grade", () => {
    const { container } = render(
      <CenteringPanel
        centering={centering({
          left_right: [78.0, 22.0],
          worst_axis: 78.0,
          psa_cap: null,
        })}
      />,
    );
    const text = container.textContent ?? "";

    expect(text).toMatch(/outside PSA's published range/i);
    expect(text).not.toMatch(/PSA \d/);
    expect(text).not.toContain("null");
  });

  it("always carries both caveats", () => {
    const { container } = render(<CenteringPanel centering={centering()} />);
    const text = container.textContent ?? "";

    // Front-only: PSA grades the back separately and this app never sees it.
    expect(text).toMatch(/front/i);
    expect(text).toMatch(/back/i);
    // One of four: corners, edges and surface are not assessed at all.
    expect(text).toMatch(/one of (?:PSA's )?four/i);
    expect(text).toMatch(/corners/i);
    expect(text).toMatch(/edges/i);
    expect(text).toMatch(/surface/i);
  });
});

function response(overrides: Partial<RecognizeResponse> = {}): RecognizeResponse {
  return {
    status: "confident",
    confidence: 0.94,
    visual_margin: 0.21,
    card: {
      id: "base1-4",
      name: "Charizard",
      number: "4",
      rarity: "Rare Holo",
      set_id: "base1",
      set_name: "Base",
      image_small: null,
      image_large: null,
    },
    // Supplied so PriceLine settles without a network call.
    price: {
      source: "tcgplayer",
      variant: "holofoil",
      low: null,
      mid: null,
      high: null,
      market: 800.0,
      source_updated_at: "2026/07/29",
    },
    candidates: [],
    collector_number_read: "4/102",
    centering: null,
    ...overrides,
  };
}

const noop = () => {};

describe("ScanResult centering panel", () => {
  it("renders no panel at all when there is no centering measurement", () => {
    const { container } = render(
      <ScanResult
        result={response({ centering: null })}
        variant="holofoil"
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    expect(container.querySelector(".centering")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/centering/i);
  });

  it("renders the panel when a measurement is present", () => {
    const { container } = render(
      <ScanResult
        result={response({ centering: centering() })}
        variant="holofoil"
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    expect(container.querySelector(".centering")).not.toBeNull();
    expect(container.textContent ?? "").toContain("allows up to PSA 9");
  });
});
