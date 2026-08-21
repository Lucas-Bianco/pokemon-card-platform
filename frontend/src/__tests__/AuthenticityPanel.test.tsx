import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import AuthenticityPanel from "../components/AuthenticityPanel";
import type { Authenticity } from "../api/types";

function payload(overrides: Partial<Authenticity> = {}): Authenticity {
  return {
    caveat: "A guide, not a verdict. Zero confirmed-counterfeit samples exist.",
    consistency: {
      printed_number: "35",
      catalog_number: "35",
      card_id: "sv9-35",
      card_name: "Sprigatito",
      match: "match",
      note: "The printed number (35) matches the catalog for Sprigatito.",
    },
    checklist: [
      {
        id: "rosette",
        title: "Rosette / dot pattern",
        what_to_check: "Under a loupe, real cards show a rosette.",
        caveat: "Needs a loupe.",
        applies: true,
      },
      {
        id: "holo_light",
        title: "Light test (holographic)",
        what_to_check: "Tilt under light for rainbow shift.",
        caveat: "Only holo cards.",
        applies: true,
      },
    ],
    ...overrides,
  };
}

// A fetch stub that returns the given Authenticity payload for /authenticity.
function stubFetch(body: Authenticity) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  } as Response);
}

function stubFetchError() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status: 500,
    json: async () => ({}),
  } as Response);
}

describe("AuthenticityPanel", () => {
  it("renders the caveat banner and the consistency result", async () => {
    stubFetch(payload());
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.querySelector(".authenticity-caveat")?.textContent).toContain(
        "guide, not a verdict",
      );
    });
    expect(container.querySelector(".consistency-status")?.textContent).toContain(
      "Printed number matches",
    );
    expect(container.querySelector(".consistency-note")?.textContent).toContain(
      "Sprigatito",
    );
  });

  it("surfaces a mismatch as the honest ambiguity, not a counterfeit verdict", async () => {
    stubFetch(
      payload({
        consistency: {
          printed_number: "43",
          catalog_number: "35",
          card_id: "sv9-35",
          card_name: "Sprigatito",
          match: "mismatch",
          note:
            "The printed number (43) does not match the catalog number (35) for Sprigatito. " +
            "This can mean the recognition was wrong, OR the card is a counterfeit — the app cannot tell which.",
        },
      }),
    );
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.querySelector(".consistency-status")?.textContent).toContain(
        "Printed number mismatch",
      );
    });
    const note = container.querySelector(".consistency-note")?.textContent ?? "";
    expect(note).toContain("cannot tell");
    // Never a fake/real verdict.
    expect(note.toLowerCase()).not.toContain("this card is a counterfeit");
  });

  it("shows an unread state when the printed number could not be read", async () => {
    stubFetch(
      payload({
        consistency: {
          printed_number: null,
          catalog_number: "35",
          card_id: "sv9-35",
          card_name: "Sprigatito",
          match: "unread",
          note: "Could not read the printed number from this scan — nothing to compare.",
        },
      }),
    );
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.querySelector(".consistency-status")?.textContent).toContain(
        "Could not read",
      );
    });
  });

  it("shows a no_card state but still renders the checklist", async () => {
    stubFetch(
      payload({
        consistency: {
          printed_number: null,
          catalog_number: null,
          card_id: null,
          card_name: null,
          match: "no_card",
          note: "No card was recognized, so there is no catalog number to check against.",
        },
        checklist: [
          {
            id: "rosette",
            title: "Rosette / dot pattern",
            what_to_check: "x",
            caveat: "y",
            applies: true,
          },
        ],
      }),
    );
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.querySelector(".consistency-status")?.textContent).toContain(
        "No card recognized",
      );
    });
    expect(container.querySelectorAll(".checklist-item").length).toBeGreaterThanOrEqual(1);
  });

  it("renders non-applicable checklist items as N/A without a checkbox", async () => {
    stubFetch(
      payload({
        checklist: [
          {
            id: "rosette",
            title: "Rosette / dot pattern",
            what_to_check: "x",
            caveat: "y",
            applies: true,
          },
          {
            id: "holo_light",
            title: "Light test (holographic)",
            what_to_check: "x",
            caveat: "y",
            applies: false,
          },
        ],
      }),
    );
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.textContent).toContain("Rosette");
    });
    const items = container.querySelectorAll(".checklist-item");
    const holo = Array.from(items).find((i) => i.textContent?.includes("Light test"));
    expect(holo?.textContent).toContain("N/A");
    // The N/A item has no interactive checkbox.
    expect(holo?.querySelector("input[type=checkbox]")).toBeNull();
    // The applicable item does.
    const rosette = Array.from(items).find((i) => i.textContent?.includes("Rosette"));
    expect(rosette?.querySelector("input[type=checkbox]")).not.toBeNull();
  });

  it("toggles a checklist checkbox as local state (not persisted)", async () => {
    stubFetch(payload());
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.textContent).toContain("Rosette");
    });
    const box = container.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(box.checked).toBe(false);
  });

  it("surfaces a load failure honestly", async () => {
    stubFetchError();
    const { container } = render(<AuthenticityPanel scanId={1} />);
    await waitFor(() => {
      expect(container.textContent).toContain("Could not load");
    });
  });
});