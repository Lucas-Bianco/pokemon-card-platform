# Grading Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an interactive pre-submission grade estimator ("Grading Studio") that combines the *measured* centering ceiling with the user's own corner/edge/surface sub-score estimates into an estimated grade band + confidence — the honest form of the "full Grade predictor" (Phase 3c), which cannot be a learned predictor because `grading_labels` = 0 and `graded_price_snapshots` = 0.

**Architecture:** Pure frontend calculator. The image-based part (centering) already runs server-side (`grading/centering.py`) and arrives in `RecognizeResponse.centering`. The combinator (sub-scores → grade band) is a transparent, deterministic pure function (`gradeEstimate.ts`) — no DB, no I/O, no price resolution, so it does not touch the sacred price-immutability/staleness constraints. The studio renders in `ScanResult` (centering from the scan) and `CardDetail` (sub-score-only, centering=null). Zero backend changes; zero new endpoints; 568 backend tests + 105-scan baseline untouched.

**Tech Stack:** React 19 + TypeScript strict, vitest 4 (jsdom, globals, NO jest-dom), @testing-library/react. No new deps. No framer-motion in the studio (keeps it jsdom-robust; CSS handles polish).

**Honesty framing (verbatim intent for copy):** "A calculator of your sub-score inputs plus the one measured sub-grade — not a prediction from the image, not a guarantee." Overall ≈ the lowest sub-grade (PSA's effective rule / BGS-CGC published overall); centering, when measured, is a *ceiling* (cannot raise the grade above what the border permits). PSA overall grades are whole numbers; BGS/CGC allow 0.5 increments.

---

## Do-not-break contract

1. **BulkScan.test.tsx is the ONLY `screen.*` (body-scoped) test.** It calls `screen.getByRole("button",{name:"Scan"})`, `screen.getByText("Charizard")`, `screen.getByText(/no card found/i)`, `screen.getByRole("button",{name:/add all to collection/i})`. The studio must NEVER produce text/accessible-names matching: "Scan", "Vault", "Alerts", "Deals", "Ledger", "Sealed", "Browse", "More", "Home", "Charizard", "no card found", "bulk", "add all to collection", "spread, not a prediction", "record this card's grade", "recorded grade", or "$0.00".
2. **Class names** use the `.grading-studio` prefix. Never reuse `.grading-upside`, `.centering`, `.grading-label-form`, `.grading-label-display`, `.grading-label-section`. The caveats list uses `.grading-studio-caveats` (NOT `.centering-caveats`).
3. **The studio is pure:** no `fetch`, no `localStorage`, no `IntersectionObserver`, no `matchMedia`, no framer-motion. Renders only when a card is identified (`{card && …}` in ScanResult; always in CardDetail which is card-gated by its own load).
4. **House test style:** `container.*` (subtree-scoped) + `container.textContent` / `not.toBeNull()` / `toBeDefined()` / `toContain` / `toMatch`. NEVER `.toBeInTheDocument()`. `getByText`/`getByRole` only inside the studio's OWN test (subtree-scoped via container or screen on a standalone render — standalone render is fine since it's not the App).
5. **Existing tests stay green** by addition: the studio adds text/elements but removes none and matches no existing queried string/class.

---

## File Structure

- Create: `frontend/src/lib/gradeEstimate.ts` — pure `estimateGrade()` + types.
- Create: `frontend/src/__tests__/gradeEstimate.test.ts` — unit tests.
- Create: `frontend/src/components/GradingStudio.tsx` — interactive estimator component.
- Create: `frontend/src/__tests__/GradingStudio.test.tsx` — component tests.
- Modify: `frontend/src/components/ScanResult.tsx` — render studio when `card` present.
- Modify: `frontend/src/__tests__/ScanResultGrading.test.tsx` — add a studio-present assertion.
- Modify: `frontend/src/components/CardDetail.tsx` — render studio (centering=null).
- Modify: `frontend/src/__tests__/CardDetail.test.tsx` — add a studio-present assertion.
- Modify: `frontend/src/styles.css` — additive `.grading-studio*` styles.
- Modify: `AI_CONTEXT.md`, `PROJECT.md`, memory.

---

### Task 1: `gradeEstimate.ts` pure function + tests

**Files:**
- Create: `frontend/src/lib/gradeEstimate.ts`
- Test: `frontend/src/__tests__/gradeEstimate.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/gradeEstimate.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- gradeEstimate`
Expected: FAIL — `Cannot find module '../lib/gradeEstimate'`.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/lib/gradeEstimate.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- gradeEstimate`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/gradeEstimate.ts frontend/src/__tests__/gradeEstimate.test.ts
git commit -m "feat(grading): pure estimateGrade calculator + tests"
```

---

### Task 2: `GradingStudio.tsx` component + tests

**Files:**
- Create: `frontend/src/components/GradingStudio.tsx`
- Test: `frontend/src/__tests__/GradingStudio.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/GradingStudio.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- GradingStudio`
Expected: FAIL — `Cannot find module '../components/GradingStudio'`.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/components/GradingStudio.tsx`:

```tsx
import { useState } from "react";

import type { Centering, Grader } from "../api/types";
import { estimateGrade, type Confidence, type SubScores } from "../lib/gradeEstimate";

interface Props {
  centering: Centering | null;
  grader?: Grader;
}

const SUBS: Array<{ key: keyof SubScores; label: string; hint: string }> = [
  { key: "corners", label: "Corners", hint: "Sharp, unfurred, no whitening." },
  { key: "edges", label: "Edges", hint: "Clean, no chipping or wear." },
  { key: "surface", label: "Surface", hint: "No scratches, prints, or indentations." },
];

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const DEFAULTS: SubScores = { corners: 9, edges: 9, surface: 9 };

function barPct(v: number): number {
  return ((v - 1) / 9) * 100;
}

/**
 * A pre-submission self-assessment — a calculator of the user's corner/edge/surface
 * estimates plus the one measured sub-grade (centering), NOT a prediction from the
 * image and NOT a guarantee. See gradeEstimate.ts for the (transparent, deterministic)
 * math and the honesty framing. Centering is measured server-side; the rest are the
 * user's own sub-score estimates, because the project has no labelled data to learn
 * corners/edges/surface from (grading/centering.py declines them for exactly that reason).
 */
export default function GradingStudio({ centering, grader = "PSA" }: Props) {
  const [subs, setSubs] = useState<SubScores>(DEFAULTS);
  const [activeGrader, setActiveGrader] = useState<Grader>(grader);

  const est = estimateGrade(subs, centering, activeGrader);

  function reset() {
    setSubs(DEFAULTS);
    setActiveGrader(grader);
  }

  return (
    <section className="grading-studio">
      <h3 className="grading-studio-headline">Grading studio — estimate a grade band</h3>
      <p className="grading-studio-sub">
        A pre-submission self-assessment. Centering is measured from your scan; rate corners,
        edges and surface yourself for an estimated grade band. A calculator of your inputs, not a
        prediction from the image and not a guarantee.
      </p>

      <div className="grading-studio-grade">
        <div className="grade-estimate">
          <span className="grade-label">Estimated {activeGrader} grade</span>
          <strong className="grade-number">≈{est.estimate}</strong>
          <span className={`grade-confidence ${est.confidence}`}>
            {CONFIDENCE_LABEL[est.confidence]}
          </span>
        </div>
        <div className="grade-centering">
          <span className="label">Centering ceiling</span>
          {est.centeringMeasured ? (
            <span>PSA {est.centeringCap}</span>
          ) : (
            <span className="unknown">unmeasured</span>
          )}
        </div>
      </div>

      <div className="grading-studio-subs">
        {SUBS.map((s) => (
          <label className="sub-score" key={s.key}>
            <span className="sub-head">
              <span className="sub-name">{s.label}</span>
              <span className="sub-value">{subs[s.key].toFixed(1)}</span>
            </span>
            <input
              type="range"
              min={1}
              max={10}
              step={0.5}
              value={subs[s.key]}
              aria-label={s.label}
              onChange={(e) =>
                setSubs((prev) => ({ ...prev, [s.key]: Number(e.target.value) }))
              }
            />
            <span className="sub-bar" aria-hidden="true">
              <span className="sub-fill" style={{ width: `${barPct(subs[s.key])}%` }} />
            </span>
            <span className="sub-hint muted small">{s.hint}</span>
          </label>
        ))}
      </div>

      {est.binding.length > 0 && (
        <p className="grading-studio-binding muted small">
          Limited by: {est.binding.join(", ")}.
        </p>
      )}

      <div className="grading-studio-grader">
        <label>
          <span>Grader</span>
          <select
            value={activeGrader}
            onChange={(e) => setActiveGrader(e.target.value as Grader)}
            aria-label="Grader"
          >
            <option value="PSA">PSA</option>
            <option value="CGC">CGC</option>
            <option value="BGS">BGS</option>
          </select>
        </label>
        <button type="button" className="link" onClick={reset}>
          Reset estimates
        </button>
      </div>

      <ul className="grading-studio-caveats">
        {est.caveats.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- GradingStudio`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GradingStudio.tsx frontend/src/__tests__/GradingStudio.test.tsx
git commit -m "feat(grading): GradingStudio interactive estimator component + tests"
```

---

### Task 3: Wire GradingStudio into ScanResult

**Files:**
- Modify: `frontend/src/components/ScanResult.tsx` (add import + render after the CenteringPanel block)
- Test: `frontend/src/__tests__/ScanResultGrading.test.tsx` (add one assertion)

- [ ] **Step 1: Write the failing test (add to ScanResultGrading.test.tsx)**

Append inside `describe("ScanResult grading annotation", …)`:

```tsx
  it("renders the GradingStudio when a card is present", async () => {
    stubFetch();

    const { container } = render(
      <ScanResult
        result={response()}
        variant="holofoil"
        scanId={42}
        onConfirm={noop}
        onPick={noop}
        onReject={noop}
        onRescan={noop}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector(".grading-studio")).not.toBeNull();
    });
    // centering is null in response() -> studio shows "unmeasured".
    expect(container.textContent ?? "").toMatch(/unmeasured/i);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ScanResultGrading`
Expected: FAIL — `.grading-studio` not found.

- [ ] **Step 3: Wire the studio into ScanResult**

In `frontend/src/components/ScanResult.tsx`:

- Add to the imports block (after the `GradingUpside` import, line 8):
```tsx
import GradingStudio from "./GradingStudio";
```

- After the CenteringPanel block (after line 146 `{result.centering && <CenteringPanel centering={result.centering} />}`) insert:
```tsx
      {/* A pre-submission self-assessment: the measured centering ceiling plus the
          user's own corner/edge/surface sub-score estimates -> an estimated grade
          band. A calculator of the user's inputs, not a prediction from the image.
          Card-gated like GradingUpside/CenteringPanel — no card, no estimate. */}
      {card && <GradingStudio centering={result.centering} grader="PSA" />}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ScanResultGrading`
Expected: PASS (all 6 prior + 1 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ScanResult.tsx frontend/src/__tests__/ScanResultGrading.test.tsx
git commit -m "feat(grading): mount GradingStudio in ScanResult"
```

---

### Task 4: Wire GradingStudio into CardDetail (sub-score-only)

**Files:**
- Modify: `frontend/src/components/CardDetail.tsx` (add import + render after GradingUpside)
- Test: `frontend/src/__tests__/CardDetail.test.tsx` (add one assertion)

- [ ] **Step 1: Write the failing test (add to CardDetail.test.tsx)**

Append inside `describe("CardDetail", …)`:

```tsx
  it("renders the GradingStudio (sub-score-only, centering unmeasured) for a collection card", async () => {
    stubFetch({});
    const { container } = render(<CardDetail cardId="base1-4" variant="normal" onBack={noop} />);

    await waitFor(() => {
      expect(container.querySelector(".grading-studio")).not.toBeNull();
    });
    // No scan -> centering is unmeasured for a collection card.
    expect(container.textContent ?? "").toMatch(/unmeasured/i);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- CardDetail`
Expected: FAIL — `.grading-studio` not found.

- [ ] **Step 3: Wire the studio into CardDetail**

In `frontend/src/components/CardDetail.tsx`:

- Add to the imports (after `GradingUpside` import, line 6):
```tsx
import GradingStudio from "./GradingStudio";
```

- After the GradingUpside line (after line 156 `<GradingUpside cardId={cardId} variant={variant} />`) insert:
```tsx
      {/* Sub-score-only self-assessment for a card you own. No scan -> centering
          unmeasured; the user rates corners/edges/surface for an estimated band.
          A calculator of their inputs, not a prediction from the image. */}
      <GradingStudio centering={null} grader="PSA" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- CardDetail`
Expected: PASS (all prior + 1 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CardDetail.tsx frontend/src/__tests__/CardDetail.test.tsx
git commit -m "feat(grading): mount GradingStudio in CardDetail"
```

---

### Task 5: Grading Studio styles (additive)

**Files:**
- Modify: `frontend/src/styles.css` (append a `.grading-studio` block; do NOT touch existing rules)

- [ ] **Step 1: Append the styles**

Append to `frontend/src/styles.css` (after the grading-label block, ~line 975):

```css
/* ----- Grading Studio (estimate a grade band) ----------------------------- */
/* Additive: the interactive pre-submission estimator. Matches the .centering /
   .grading-upside glass-card language. No existing rule is touched. */
.grading-studio {
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-3);
  box-shadow: var(--shadow-glass);
  padding: var(--sp-4);
  animation: studio-in 0.32s ease both;
}
@keyframes studio-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: none; }
}
.grading-studio-headline { margin: 0; font-size: 0.95rem; font-weight: 600; }
.grading-studio-sub { margin: 4px 0 0; font-size: 0.78rem; color: var(--fg-dim); }

.grading-studio-grade {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--sp-3);
  align-items: center;
  margin-top: var(--sp-4);
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.grade-estimate { display: flex; flex-direction: column; gap: 2px; }
.grade-estimate .grade-label { font-size: 0.75rem; color: var(--fg-dim); }
.grade-number {
  font-size: 2.1rem;
  font-weight: 700;
  line-height: 1;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.grade-confidence { font-size: 0.72rem; font-weight: 600; }
.grade-confidence.high { color: var(--ok); }
.grade-confidence.medium { color: var(--warn); }
.grade-confidence.low { color: var(--down); }
.grade-centering { text-align: right; }
.grade-centering .label { font-size: 0.72rem; color: var(--fg-dim); display: block; }
.grade-centering .unknown { color: var(--fg-dim); }

.grading-studio-subs { margin-top: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-3); }
.sub-score { display: flex; flex-direction: column; gap: 6px; }
.sub-head { display: flex; justify-content: space-between; align-items: baseline; }
.sub-name { font-size: 0.82rem; font-weight: 600; }
.sub-value { font-size: 0.82rem; color: var(--fg-dim); font-variant-numeric: tabular-nums; }
.sub-score input[type="range"] { width: 100%; accent-color: var(--accent); }
.sub-bar { height: 6px; border-radius: 999px; background: var(--line); overflow: hidden; }
.sub-fill { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent-2), var(--accent)); transition: width 0.2s ease; }
.sub-hint { font-size: 0.72rem; }

.grading-studio-binding { margin: var(--sp-2) 0 0; }
.grading-studio-grader { margin-top: var(--sp-3); display: flex; align-items: end; gap: var(--sp-3); }
.grading-studio-grader label { display: flex; flex-direction: column; gap: 2px; }
.grading-studio-grader .label, .grading-studio-grader span:first-child { font-size: 0.72rem; color: var(--fg-dim); }
.grading-studio-grader select {
  background: var(--surface); color: var(--fg); border: 1px solid var(--line);
  border-radius: var(--r-1); padding: 4px 6px; font: inherit;
}

.grading-studio-caveats { margin: var(--sp-3) 0 0; padding-left: 16px; }
.grading-studio-caveats li { font-size: 0.72rem; color: var(--fg-dim); }
.grading-studio-caveats li + li { margin-top: 2px; }

@media (prefers-reduced-motion: reduce) {
  .grading-studio { animation: none; }
  .sub-fill { transition: none; }
}
@media (min-width: 880px) {
  .grading-studio-subs { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--sp-4); }
}
```

- [ ] **Step 2: Run the full suite + build**

Run: `cd frontend && npm test && npm run build`
Expected: all tests PASS; build succeeds (no TS errors — noUnusedLocals etc.).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat(grading): Grading Studio styles (bars, confidence pill, responsive)"
```

---

### Task 6: Docs + memory + push

**Files:**
- Modify: `AI_CONTEXT.md`, `PROJECT.md`, `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md`, `MEMORY.md`

- [ ] **Step 1: Update AI_CONTEXT.md** — add a roadmap row + bump frontend test count ("568 backend + 155 frontend" — 146 + 9 gradeEstimate + 8 GradingStudio + 1 ScanResult + 1 CardDetail = 165; use the actual `npm test` count). Append a short "Grading Studio" section.
- [ ] **Step 2: Update PROJECT.md** — append a "Grading Studio — shipped 2026-08-21" section.
- [ ] **Step 3: Update memory** — append a "**Grading Studio (2026-08-21):**" paragraph: the honest form of the Grade predictor (calculator, not learned — because 0 labels + 0 graded prices), gradeEstimate.ts pure fn (min-of-subgrades + centering ceiling + PSA-whole/BGS-CGC-half snap + honest confidence), GradingStudio.tsx (sliders + bars + confidence pill, pure/no-fetch, `.grading-studio` classes, "Reset estimates" button), mounted in ScanResult (centering from scan) + CardDetail (sub-score-only), do-not-break contract (BulkScan screen.* + distinct strings/classes), commits, test count, 568 backend + 105-scan baseline untouched. Update MEMORY.md hook line.
- [ ] **Step 4: Final verify + push**

```bash
cd C:/ClaudeKnowledge/frontend && npm test && npm run build
cd C:/ClaudeKnowledge && git add -A && git status   # confirm frontend-only
git commit -m "docs: Grading Studio phase (estimate a grade band)"
git push origin main
```

---

## Self-Review

**1. Spec coverage:** The "full Grade predictor" (memory's standing next) is delivered in its only honest form — a transparent calculator (no labels to learn from; graded prices = 0 so no dollar-upside-at-grade is claimed). Centering measured server-side (existing); sub-scores user-supplied; band + confidence honest. ✅ Mounted in both scan flow and card detail. ✅ Tests + styles + docs. ✅

**2. Placeholder scan:** Every step has complete code. No TBD/TODO. ✅

**3. Type consistency:** `SubScores` (corners/edges/surface), `Grader` reuses `../api/types` Grader, `Centering` from `../api/types`. `estimateGrade(subs, centering, grader)` signature consistent across test + impl + component. `binding` is `string[]`. ✅

**4. Do-not-break contract:** Studio is pure (no fetch/IO/motion), `.grading-studio` classes, distinct wording, "Reset estimates" button (≠ any nav/CTA), card-gated in ScanResult. BulkScan `screen.*` assertions unaffected (studio produces none of the queried strings). ✅