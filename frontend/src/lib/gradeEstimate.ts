import type { Centering } from "../api/types";

export type Grader = "PSA" | "CGC" | "BGS";

export interface SubScores {
  corners: number; // 1.0–10.0
  edges: number;
  surface: number;
}

export type Confidence = "high" | "medium" | "low";

export interface GradeEstimate {
  estimate: number; // snapped to the grader's valid step, clamped to [1, 10]
  confidence: Confidence;
  binding: string[]; // sub-score names equal to the min (the limiting factor)
  centeringMeasured: boolean;
  centeringCap: number | null; // the measured ceiling, or null
  caveats: string[];
}

// PSA overall grades are whole numbers; BGS/CGC allow 0.5 increments.
function snap(value: number, grader: Grader): number {
  if (grader === "PSA") return Math.round(value);
  return Math.round(value * 2) / 2;
}

function clampHalf(v: number): number {
  return Math.max(1, Math.min(10, Math.round(v * 2) / 2));
}

/**
 * A transparent grade calculator, NOT a prediction from the image.
 *
 * The overall grade is roughly the LOWEST sub-grade (PSA's effective rule and
 * the BGS/CGC published overall). Centering, when measured, is a CEILING: it
 * cannot raise the grade above what the border permits (see grading/centering.py
 * — `psa_cap` is "the best grade this centering permits"). Centering is the one
 * sub-grade measurable from the image; corners/edges/surface are the user's own
 * estimates, so the result is a calculator of their inputs, not a learned
 * prediction (the project has 0 grading labels to learn from).
 *
 * Confidence is honest, not decorated: high only when centering is measured AND
 * certain AND the user's sub-scores agree within half a grade. Low when the
 * sub-scores span more than a grade or centering is unmeasured.
 */
export function estimateGrade(
  subs: SubScores,
  centering: Centering | null,
  grader: Grader = "PSA",
): GradeEstimate {
  const corners = clampHalf(subs.corners);
  const edges = clampHalf(subs.edges);
  const surface = clampHalf(subs.surface);

  const centeringMeasured = centering !== null && centering.psa_cap !== null;
  const centeringCap = centeringMeasured ? centering!.psa_cap : null;

  const values: number[] = [corners, edges, surface];
  if (centeringCap !== null) values.push(centeringCap);
  const rawMin = Math.min(...values);
  const estimate = Math.max(1, Math.min(10, snap(rawMin, grader)));

  const binding: string[] = [];
  if (corners === rawMin) binding.push("corners");
  if (edges === rawMin) binding.push("edges");
  if (surface === rawMin) binding.push("surface");
  if (centeringCap !== null && centeringCap === rawMin) binding.push("centering");

  const userVals = [corners, edges, surface];
  const spread = Math.max(...userVals) - Math.min(...userVals);
  const centeringCertain = centering !== null && centering.psa_cap_certain;

  let confidence: Confidence;
  if (centeringMeasured && centeringCertain && spread <= 0.5) confidence = "high";
  else if (centeringMeasured && spread <= 1.5) confidence = "medium";
  else if (!centeringMeasured && spread <= 0.5) confidence = "medium";
  else confidence = "low";

  const caveats: string[] = [
    "Your sub-score estimates, not a prediction from the image.",
    "Overall is roughly the lowest sub-grade, with grader discretion — not a guarantee.",
  ];
  if (!centeringMeasured) {
    caveats.push("Centering unmeasured — an off-center card could grade lower than this estimate.");
  } else if (!centeringCertain) {
    caveats.push("Centering reading straddles a grade boundary, so the ceiling is uncertain.");
  }
  if (grader === "PSA") {
    caveats.push("PSA gives whole-number grades; the estimate is rounded to the nearest whole.");
  }

  return { estimate, confidence, binding, centeringMeasured, centeringCap, caveats };
}