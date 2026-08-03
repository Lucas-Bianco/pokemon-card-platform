// Shared marketing-site content. Copy preserved verbatim from docs/index.html.
// Roadmap + pipeline + stack data live here so section components stay presentational.

export type Phase = {
  n: string;
  title: string;
  subtitle: string;
  status: "done" | "progress" | "planned";
  /** Optional count-up stat shown on done phases (e.g. coverage delta). */
  stat?: { label: string; from: string; to: string };
};

export const ROADMAP: Phase[] = [
  { n: "00", title: "Foundation", subtitle: "Card catalog, pricing layer, collection store", status: "done" },
  { n: "01a", title: "Recognition engine", subtitle: "Photo → identified, valued card · 20,391 cards indexed", status: "done" },
  { n: "01b", title: "Scan PWA", subtitle: "Camera capture, top-3 picker · 100% precision on real photos", status: "done" },
  {
    n: "01c",
    title: "Robust card detection",
    subtitle: "Strategy chain scored by recognition · coverage 31% → 61%, 0 regressions",
    status: "done",
    stat: { label: "Coverage", from: "31%", to: "61%" },
  },
  { n: "02", title: "Portfolio tracker", subtitle: "Cost basis, P/L, price history charts · honest empty states", status: "done" },
  {
    n: "03a",
    title: "Card centering",
    subtitle: "Geometric PSA cap from border measurement · correct, coverage blocked on real photos",
    status: "done",
  },
  {
    n: "03b",
    title: "Grading data infrastructure",
    subtitle:
      "Rectified-crop persistence, grade-label schema + self-annotation, graded-price provider, grading-upside spread",
    status: "done",
  },
  {
    n: "03",
    title: "Grade predictor",
    subtitle:
      "Corner / edge / surface scoring + P(grade) — data infrastructure unblocked, full predictor still planned",
    status: "progress",
  },
  { n: "04", title: "Bulk cataloger", subtitle: "Detect and log every card in one photo", status: "planned" },
  { n: "05", title: "Deal sniper & sealed EV", subtitle: "Deal sniper (rip-vs-flip) shipped — sealed EV still planned", status: "progress" },
  { n: "06", title: "Set-completion optimizer", subtitle: "Cheapest path to finishing a set", status: "planned" },
  { n: "07", title: "Counterfeit detector", subtitle: "Holo pattern, print rosette, texture analysis", status: "planned" },
  { n: "08", title: "On-device inference", subtitle: "Quantized model in-browser — scanning with no server", status: "planned" },
];

export const SHIPPED_COUNT = ROADMAP.filter((p) => p.status === "done").length;
export const TOTAL_COUNT = ROADMAP.length;

export type PipeStep = {
  title: string;
  detail: string;
};

export const PIPELINE: PipeStep[] = [
  {
    title: "Detect & rectify",
    detail:
      "Find the card's corners in-frame and perspective-warp it flat. Runs on-device in WebAssembly to drive a live camera overlay.",
  },
  {
    title: "Visual embedding match",
    detail:
      "Embed the crop and search every card in the catalog by visual similarity. Returns ranked candidates, never one blind guess.",
  },
  {
    title: "Targeted OCR",
    detail:
      "Read the collector number — a unique key for any card — from a known position on the rectified image.",
  },
  {
    title: "Fusion & calibrated confidence",
    detail:
      "Combine both signals. Agreement auto-confirms; disagreement surfaces the top three and logs the user's pick as training data.",
  },
  {
    title: "Variant disambiguation",
    detail:
      "Specular analysis separates holo from reverse-holo foiling — the difference that most scanners silently get wrong.",
  },
];

export const PIPELINE_NOTE =
  "Rectification is the load-bearing step: it makes both engines more accurate, shrinks the network payload, and produces exactly the normalized image the grading module needs later.";

export const STACK_FRONTEND = ["React", "TypeScript", "OpenCV.js / WASM", "PWA"];
export const STACK_BACKEND = ["FastAPI", "CLIP / DINOv2", "FAISS", "PaddleOCR", "Postgres"];

export const STACK_FRONTEND_BLURB = "Installable PWA — one codebase for phone camera and desktop.";
export const STACK_BACKEND_BLURB = "Python, deliberately — the CV and ML ecosystem the later phases depend on.";

// The bold lead-in "Runs entirely on your own machine." is rendered separately
// in Stack.tsx, so this note begins with the supporting sentence to avoid a
// duplicated lead phrase in the rendered output.
export const STACK_LOCAL_NOTE =
  "Compute is local — recognition, embedding, search, and OCR never leave the device. Only the card catalog and price data sync over the network, so scanning still works offline, in a card shop, on bad signal.";