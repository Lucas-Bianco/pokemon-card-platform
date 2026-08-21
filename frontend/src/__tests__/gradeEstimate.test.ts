import { describe, expect, it } from "vitest";

import { estimateGrade } from "../lib/gradeEstimate";
import type { Centering } from "../api/types";

const cap = (psa_cap: number | null, certain = true): Centering | null =>
  psa_cap === null
    ? null
    : {
        left_right: [55, 45],
        top_bottom: [52, 48],
        worst_axis: 55,
        uncertainty: 2.5,
        psa_cap,
        psa_cap_certain: certain,
      };

describe("estimateGrade", () => {
  it("estimates the min of the sub-scores when centering is unmeasured", () => {
    const e = estimateGrade({ corners: 9, edges: 9, surface: 8.5 }, null, "BGS");
    expect(e.estimate).toBe(8.5);
    expect(e.centeringMeasured).toBe(false);
    expect(e.binding).toEqual(["surface"]);
  });

  it("snaps to a whole number for PSA", () => {
    // min sub-score 8.5 -> PSA rounds to 9 (whole-number overall grade).
    const e = estimateGrade({ corners: 9, edges: 9, surface: 8.5 }, null, "PSA");
    expect(e.estimate).toBe(9);
  });

  it("applies the measured centering cap as a ceiling", () => {
    // sub-scores all 10, but centering only allows PSA 9 -> estimate 9, bound by centering.
    const e = estimateGrade({ corners: 10, edges: 10, surface: 10 }, cap(9), "PSA");
    expect(e.estimate).toBe(9);
    expect(e.centeringMeasured).toBe(true);
    expect(e.centeringCap).toBe(9);
    expect(e.binding).toEqual(["centering"]);
  });

  it("reports high confidence when centering is measured+certain and sub-scores agree", () => {
    const e = estimateGrade({ corners: 9, edges: 9, surface: 9 }, cap(10, true), "PSA");
    expect(e.confidence).toBe("high");
  });

  it("reports low confidence when sub-scores span more than a grade", () => {
    const e = estimateGrade({ corners: 10, edges: 7, surface: 9 }, cap(10, true), "PSA");
    expect(e.confidence).toBe("low");
  });

  it("notes the centering-unmeasured caveat when centering is null", () => {
    const e = estimateGrade({ corners: 9, edges: 9, surface: 9 }, null, "PSA");
    expect(e.caveats.some((c) => /centering unmeasured/i.test(c))).toBe(true);
  });

  it("notes the boundary-uncertainty caveat when centering is uncertain", () => {
    const e = estimateGrade({ corners: 9, edges: 9, surface: 9 }, cap(9, false), "PSA");
    expect(e.caveats.some((c) => /straddles a grade boundary/i.test(c))).toBe(true);
    expect(e.confidence).not.toBe("high");
  });

  it("clamps out-of-range sub-scores to [1, 10] in half-steps", () => {
    const e = estimateGrade({ corners: 12, edges: -1, surface: 9 }, null, "PSA");
    // corners 12 -> 10, edges -1 -> 1 -> min is 1 -> estimate 1.
    expect(e.estimate).toBe(1);
  });

  it("lists multiple binding sub-scores when tied at the min", () => {
    const e = estimateGrade({ corners: 8, edges: 8, surface: 9 }, null, "BGS");
    expect(e.binding).toEqual(["corners", "edges"]);
  });
});