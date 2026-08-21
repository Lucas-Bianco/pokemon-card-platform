import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";

import GradingStudio from "../components/GradingStudio";
import type { Centering } from "../api/types";

const cap = (psa_cap: number, certain = true): Centering => ({
  left_right: [55, 45],
  top_bottom: [52, 48],
  worst_axis: 55,
  uncertainty: 2.5,
  psa_cap,
  psa_cap_certain: certain,
});

describe("GradingStudio", () => {
  it("renders the headline and three sub-score sliders", () => {
    const { container } = render(<GradingStudio centering={null} />);
    expect(container.textContent ?? "").toMatch(/estimate a grade band/i);
    const sliders = container.querySelectorAll('input[type="range"]');
    expect(sliders.length).toBe(3);
  });

  it("shows the centering ceiling when measured", () => {
    const { container } = render(<GradingStudio centering={cap(9)} />);
    expect(container.textContent ?? "").toContain("Centering ceiling");
    expect(container.textContent ?? "").toContain("PSA 9");
  });

  it("shows 'unmeasured' for centering when null", () => {
    const { container } = render(<GradingStudio centering={null} />);
    expect(container.textContent ?? "").toMatch(/unmeasured/i);
  });

  it("updates the estimate when a slider changes", () => {
    const { container } = render(<GradingStudio centering={null} />);
    // Defaults are 9/9/9 -> estimate 9. Lower surface to 7 -> estimate 7.
    const surface = [...container.querySelectorAll('input[type="range"]')][2] as HTMLInputElement;
    fireEvent.change(surface, { target: { value: "7" } });
    expect(container.textContent ?? "").toContain("≈7");
  });

  it("applies the centering cap as a ceiling (sub-scores 10 but cap 9 -> 9)", () => {
    const { container } = render(<GradingStudio centering={cap(9)} />);
    // Move all sliders to 10.
    container.querySelectorAll('input[type="range"]').forEach((s) =>
      fireEvent.change(s, { target: { value: "10" } }),
    );
    expect(container.textContent ?? "").toContain("≈9");
    expect(container.textContent ?? "").toMatch(/limited by:.*centering/i);
  });

  it("renders honest caveats and never claims a guarantee", () => {
    const { container } = render(<GradingStudio centering={null} />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/not a prediction from the image/i);
    expect(text).toMatch(/not a guarantee/i);
    expect(container.querySelector(".grading-studio-caveats")).not.toBeNull();
  });

  it("switches grader and re-snaps the estimate (PSA whole vs BGS half)", () => {
    const { container } = render(<GradingStudio centering={null} />);
    // Set surface to 7.5 via slider; corners/edges stay 9 -> min 7.5.
    const surface = [...container.querySelectorAll('input[type="range"]')][2] as HTMLInputElement;
    fireEvent.change(surface, { target: { value: "7.5" } });
    // PSA rounds 7.5 -> 8.
    expect(container.textContent ?? "").toContain("≈8");
    const select = container.querySelector("select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "BGS" } });
    // BGS keeps the half-step.
    expect(container.textContent ?? "").toContain("≈7.5");
  });

  it("reset restores the default sub-scores", () => {
    const { container } = render(<GradingStudio centering={null} />);
    const surface = [...container.querySelectorAll('input[type="range"]')][2] as HTMLInputElement;
    fireEvent.change(surface, { target: { value: "7" } });
    expect(container.textContent ?? "").toContain("≈7");
    const reset = [...container.querySelectorAll("button")].find((b) =>
      /reset estimates/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(reset);
    expect(container.textContent ?? "").toContain("≈9");
  });
});