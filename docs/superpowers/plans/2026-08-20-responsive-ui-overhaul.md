# Responsive UI Overhaul — Refined Dark + Polished Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Pokémon card platform's frontend into a fully custom, premium, responsive UI — a refined dark-glass identity that keeps the Pokémon-yellow accent, adapts fluidly from phone to any desktop width (desktop sidebar nav + multi-column grids, mobile bottom-nav preserved), and adds polished Framer Motion transitions (page/view fade+slide, card mount stagger, hover lift, tap scale, sheet spring) — **without breaking any of the 126 frontend tests or the 105-scan baseline.**

**Architecture:** Evolutionary, not a rewrite. We layer new responsive structure, motion, and glass surfaces on top of the existing component tree. Every existing class name, `input[name]`, `aria-label`, button accessible-name, `data-label`, and honest-empty-state string the tests query is **frozen** — new CSS/structure/motion is additive. The one structural change is the nav: AppShell decides between a desktop sidebar (`<aside class="app-sidebar">`) and the mobile `.bottom-nav` via a JS media-query hook so only one nav is ever mounted (jsdom has no viewport → mobile → bottom-nav → `getByRole("button", { name: "Scan" })` still resolves to a single element). Framer Motion (`framer-motion@^12`) is a new dependency; motion is wrapped on top of existing elements (a `motion.button` still renders `<button>`, so roles/text are preserved).

**Tech Stack:** React 19.2, TypeScript 5.9 (strict, `noUnusedLocals/Parameters`), Vite 8, vitest 4 (jsdom, globals), framer-motion 12 (new), existing hand-rolled CSS in `src/styles.css` (~1714 lines, design tokens in `:root`). No router (AppShell `view` state). API client `BASE="/api"` Vite-proxied — unchanged. Frontend-only phase; backend, `data/`, and the 105-scan baseline are untouched.

---

## 0. The "do-not-break" contract (read before every task)

The 126 tests in `frontend/src/__tests__/` assert DOM structure/text/`classList`/`querySelector` — never computed styles. **Freeze all of the following; layer new on top, never rename/remove:**

**Class names (queried by tests):** `.app`, `.app-shell`, `.app-content`, `.bottom-nav`, `.persistent-header`, `.app-header`, `.header-toggle`, `.nav-glyph`, `.nav-glyph-wrap`, `.nav-badge`, `.deal-card`, `.deal-chip.rip`, `.deal-chip.flip`, `.deal-rip-edge`, `.deal-flip-10`, `.deal-flip-9`, `.alert-row`, `.alert-row.unread`, `.alert-chip`, `.browse-result`, `.browse-input`, `.portfolio-table`, `.holding-row`, `.valuation .up`, `.valuation .unknown`, `.unpriced`, `.grading-upside`, `.grading-upside-value .up`, `.grading-upside-value .unknown`, `.grading-upside-headline`, `.grading-label-form`, `.grading-label-display`, `.price-chart`, `.listing-row`, `.ledger-delete`, `.watch-type-chip`, `.bulk-grid`, `.bulk-cell`, `.bulk-variant`, `.bulk-log-status`, `.bulk-add-all`, `.skeleton`, `.skeleton-block`, `.skeleton-block[aria-label="Loading …"]`.

**`input[name]` (queried exactly):** WatchCardSheet — `target_price`, `drop_at`, `lead_time_min`, `auction_window_min`. SealedLedger — `ledger-query`, `ledger-cost`, `ledger-qty`, `ledger-type`, `ledger-source`.

**`aria-label` (frozen):** `"Refresh alerts"`, `"Search a card to find deals"`, `"Search cards by name"`, `"Search a sealed product"`, the ledger form input labels (`"Product"`, `"Cost per unit"`, `"Quantity"`, `"Product type"`, `"Source"`), `"Watch a card"` (sheet dialog), `"Close"` (sheet close), `"Corner 1"`..`"Corner 4"`, `"Loading …"` skeletons.

**Button accessible names (frozen, matched by regex/exact):** the 8 bottom-nav tab names `"Scan"`, `"Vault"`, `"Alerts"`, `"Deals"`, `"Sealed"`, `"Ledger"`, `"Browse"`, `"More"` (BulkScan relies on `getByRole("button", { name: "Scan" })` — **exactly one** "Scan" button may be in the DOM at once), `/bulk/i` toggle, `/add all to collection/i`, `/watch this card/i`, `/record grade/i`, `/back/i`, `/retry/i`, `/refresh/i`, `/log purchase/i`, `/sync to google/i`, `/^watch$/i`, `/find/i`.

**`data-label` (frozen, PortfolioView):** exactly 8 cells per row labeled `Qty`, `Card`, `Variant`, `Set`, `Paid`, `Market`, `Unrealised`, `Actions`.

**Honest-empty-state strings (frozen):** `"no purchases logged"`, `"not yet valued"`, `"No card found"`, `"No price history yet."`, `"Unpriced"`, `"Checking grading spread…"`, `"Recent sold (eBay)"`, `"no market price"`/`"no price available"`, `"spread, not a prediction"`, `"No recent sold comps found on eBay for this card."`, every `—` (em dash) for null prices. Never `$0.00` for a null/unvalued item.

**Existing motion to preserve (don't delete the keyframes — chrome uses them):** `@keyframes warming-pulse`, `@keyframes skeleton-shimmer`, `@keyframes sheet-rise`, and their four `@media (prefers-reduced-motion: reduce)` guards.

**Existing breakpoints (the natural insertion points):** `max-width:480px` (L744, L1491), `max-width:639px` (L760), `min-width:960px` (L827 — the only desktop hook today), `max-width:600px` (L1690), `max-width:720px` (L1710). New desktop CSS goes in a new trailing banner after L1714 **and** extends the `min-width:960px` block + adds `min-width:1024px` / `min-width:1440px`.

**Sacred constraints (from project memory):** never resolve a price ad-hoc — this phase touches **no** backend/price code, so this is automatically held. Never delete anything under `data/`. Never fabricate prices / never `$0` for nulls. This phase is frontend-only → all backend sacred constraints are untouched by construction.

---

## File Structure

**New files:**
- `frontend/src/lib/useIsDesktop.ts` — `useIsDesktop()` hook (matchMedia `min-width:1024px`, SSR/jsdom-safe, defaults `false`). Responsibility: the single source of truth for "render desktop sidebar vs mobile bottom-nav" so the two navs are never both mounted.
- `frontend/src/components/motion.ts` — shared Framer Motion variants + a `PageTransition` component + a `MotionCard` wrapper (hover-lift / tap-scale) + a `StaggerList`/`StaggerItem` pair. Responsibility: one place for the motion vocabulary so per-surface tasks import rather than reinvent; all variants respect `useReducedMotion`.

**Modified files:**
- `frontend/package.json` — add `framer-motion@^12.0.0` to `dependencies`.
- `frontend/src/components/AppShell.tsx` — render either `<DesktopNav>` or `.bottom-nav` based on `useIsDesktop()`; wrap the view branch in `<AnimatePresence mode="wait">` + `<PageTransition>` keyed by `view`/`selectedCard`; add `<DesktopNav>` (a `<aside class="app-sidebar">` reusing the existing `TabButton` + glyphs — same labels, same glyphs, so accessible names are byte-identical).
- `frontend/src/styles.css` — `:root` adds new tokens (glass, gradient, motion-durations, radius scale, sidebar width, desktop content max-width); new `.app-sidebar` + desktop layout block (`min-width:1024px`/`1440px`); elevated `.surface`/glass treatments layered on existing card classes; multi-column desktop grids for the list surfaces; reduced-motion guard for new motion. **No existing rule is deleted or renamed** — only extended/added.
- `frontend/src/components/WatchCardSheet.tsx` — `.sheet-overlay` + `.sheet` become `motion.div` with spring entrance + fade exit (gated by `useReducedMotion`). DOM structure, `role="dialog"`, `aria-label`, `aria-modal`, all `input[name]`, button text — unchanged.
- `frontend/src/components/{Deals,AlertsFeed,Browse,SealedDeals,SealedLedger,PortfolioView}.tsx` — wrap list items in `StaggerItem` / `MotionCard` for mount-stagger + hover/tap; **no** change to class names, text, inputs, or callbacks. (CardDetail, ScanResult, and the other detail components get hover/tap via `MotionCard` too where a card-like element exists.)
- `frontend/src/components/CardDetail.tsx` — entrance via `PageTransition`-style fade/slide (it already overrides the tab when `selectedCard` is set; the AnimatePresence key handles the transition).
- `frontend/AI_CONTEXT.md` (repo root, not frontend) — append a UI-overhaul section + bump frontend test count note if it changes (it should not: 126 stays green).
- `frontend/PROJECT.md` (if present) / repo `PROJECT.md` — status line.
- `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md` — record the overhaul phase (controller does this in T6, not an implementer).

**Files NOT touched:** everything under `backend/`, `data/`, `site/`, `docs/` (except this plan), all `__tests__/`, `api/client.ts`, `api/types.ts`, `lib/format.ts`, `lib/time.ts`, `lib/cameraCrop.ts`, `App.tsx`, `main.tsx`, `index.html`, `vite.config.ts`, `tsconfig.json`.

---

## Task 1: Foundation — framer-motion dep, design/motion tokens, useIsDesktop + motion helpers

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/lib/useIsDesktop.ts`
- Create: `frontend/src/components/motion.ts`
- Modify: `frontend/src/styles.css` (`:root` token additions only — a new trailing block, do not edit existing rules)

- [ ] **Step 1: Add framer-motion dependency**

Edit `frontend/package.json` `dependencies` to add (keep alphabetical-ish; place after `@fontsource-variable/jetbrains-mono`):

```json
  "framer-motion": "^12.0.0",
```

- [ ] **Step 2: Install and confirm it resolves under React 19**

Run: `npm --prefix frontend install`
Expected: install succeeds (framer-motion 12 peers allow React 19). If npm reports a peer conflict on React 19, run `npm --prefix frontend install --legacy-peer-deps` and note it; do NOT downgrade React.

- [ ] **Step 3: Create `useIsDesktop.ts`**

`frontend/src/lib/useIsDesktop.ts`:

```ts
import { useEffect, useState } from "react";

// Single source of truth for "render the desktop sidebar vs the mobile bottom-nav."
// CRITICAL: exactly one nav must be mounted at a time — tests do
//   getByRole("button", { name: "Scan" }) which throws if both navs are in the DOM.
// jsdom has no real viewport: window.matchMedia exists but returns matches:false and
// never fires listeners, so this hook returns false in tests → mobile bottom-nav only.
const QUERY = "(min-width: 1024px)";

export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setDesktop(e.matches);
    // addEventListener is the modern API; older Safari used addListener — guard both.
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener(onChange);
    };
  }, []);

  return desktop;
}
```

- [ ] **Step 4: Create `motion.ts` — the shared motion vocabulary**

`frontend/src/components/motion.ts`:

```ts
import type { ReactNode } from "react";
import {
  motion,
  useReducedMotion,
  type Variants,
  type Transition,
} from "framer-motion";

// All motion respects prefers-reduced-motion: when reduced, variants collapse to
// opacity-only (no transforms), and MotionCard becomes a plain passthrough so hover/tap
// do nothing. Tests run under jsdom where useReducedMotion() === false, so transitions
// still render — but they never change DOM structure, roles, or text, so the 126 tests
// stay green.

const EASE: Transition = { duration: 0.28, ease: [0.22, 1, 0.36, 1] };

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  enter: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.04, delayChildren: 0.02 },
  },
};

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: EASE },
};

// PageTransition wraps a tab view / detail view for fade+slide on mount/unmount.
// Used inside <AnimatePresence mode="wait"> keyed by the view id in AppShell.
export function PageTransition({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      key={id}
      variants={pageVariants}
      initial={reduced ? { opacity: 0 } : "initial"}
      animate={reduced ? { opacity: 1 } : "enter"}
      exit={reduced ? { opacity: 0 } : "exit"}
      transition={EASE}
      style={{ width: "100%" }}
    >
      {children}
    </motion.div>
  );
}

// StaggerList wraps a list; StaggerItem wraps each child for mount stagger.
// The wrapper renders a plain <div> (not a <ul>); use it around an existing <ul>
// or set `as`-free — callers keep their own <ul class="deal-list"> etc. and put
// StaggerItem inside each <li> so list semantics + classes are untouched.
export function StaggerList({
  children,
}: {
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={staggerContainer}
      initial={reduced ? "show" : "hidden"}
      animate="show"
      style={{ display: "contents" }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduced = useReducedMotion();
  if (reduced) return <div className={className}>{children}</div>;
  return (
    <motion.div
      variants={staggerItem}
      className={className}
      style={{ width: "100%" }}
    >
      {children}
    </motion.div>
  );
}

// MotionCard: hover-lift + tap-scale on any card-like element. Pass an `as` tag so it
// renders the right element (motion.button / motion.div / motion.a). When reduced
// motion is on, returns a plain element with the same tag + className — no transforms.
import { motion as m } from "framer-motion";

export function MotionCard({
  as = "div",
  className,
  children,
  ...rest
}: {
  as?: "div" | "button" | "a";
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  const reduced = useReducedMotion();
  if (reduced) {
    const Tag = as;
    return (
      <Tag className={className} {...rest}>
        {children}
      </Tag>
    );
  }
  const Tag = m[as];
  return (
    <Tag
      className={className}
      whileHover={{ y: -4 }}
      whileTap={{ scale: 0.985 }}
      transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
```

> Note: `import { motion as m } from "framer-motion"` is duplicated for clarity — the implementer may consolidate the two `motion` imports into one (`import { motion, useReducedMotion, ... }`) and drop the `m` alias. The behavior is identical.

- [ ] **Step 5: Add design + motion tokens to `styles.css`**

Append a new trailing banner block at the very end of `frontend/src/styles.css` (after the Phase 05d ledger block). Do NOT edit any existing `:root` line — add a second `:root` block (CSS merges custom properties):

```css
/* === UI Overhaul 2026-08-20 — refined dark + responsive + motion tokens === */
:root {
  /* Glass surfaces — layered on top of existing --surface; never replaces it */
  --glass-bg: rgba(20, 24, 33, 0.72);
  --glass-bg-strong: rgba(16, 19, 27, 0.86);
  --glass-border: rgba(255, 255, 255, 0.06);
  --glass-blur: 14px;

  /* Gradient accents — Pokémon yellow stays the hero; secondary for depth */
  --grad-accent: linear-gradient(135deg, #ffcb05 0%, #ffd84d 48%, #f5a623 100%);
  --grad-accent-soft: linear-gradient(135deg, rgba(255,203,5,0.16), rgba(59,109,240,0.12));
  --grad-surface: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0));
  --grad-page: radial-gradient(1200px 600px at 50% -10%, rgba(59,109,240,0.10), transparent 70%),
               radial-gradient(900px 500px at 100% 0%, rgba(255,203,5,0.06), transparent 65%);

  /* Radii + elevation scale (extends --shadow-1/2/3) */
  --r-1: 8px;
  --r-2: 12px;
  --r-3: 18px;
  --r-pill: 999px;
  --shadow-glass: 0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 30px rgba(0,0,0,0.36);

  /* Motion vocabulary (durations; easings live in motion.ts) */
  --t-fast: 120ms;
  --t-base: 220ms;
  --t-slow: 360ms;

  /* Responsive layout */
  --sidebar-w: 240px;
  --content-max: 1180px;
  --content-pad: clamp(16px, 3vw, 40px);
}
```

- [ ] **Step 6: Verify typecheck + build + tests are still green (no behavior wired yet)**

Run: `npm --prefix frontend run build`
Expected: `tsc -b` passes (no unused-locals errors from the new files — `MotionCard`'s `rest` spread is used; remove the `m`-alias duplicate import if TS complains about duplicate `motion`). `vite build` succeeds.

Run: `npm --prefix frontend test -- --run`
Expected: 126 tests pass (nothing imports the new modules yet, so behavior is identical).

- [ ] **Step 7: Commit**

```bash
cd C:/ClaudeKnowledge && git add frontend/package.json frontend/package-lock.json \
  frontend/src/lib/useIsDesktop.ts frontend/src/components/motion.ts frontend/src/styles.css
git commit -m "$(cat <<'EOF'
feat(ui): add framer-motion, responsive/motion tokens, useIsDesktop + motion helpers

Foundation for the responsive UI overhaul. Adds framer-motion@^12 (React 19
compatible), a useIsDesktop() matchMedia hook (the single source of truth for
desktop sidebar vs mobile bottom-nav so the two navs are never both mounted —
jsdom has no viewport so tests stay on mobile/bottom-nav), a shared motion
vocabulary (PageTransition, StaggerList/Item, MotionCard — all reduced-motion
gated), and new design/motion/glass/responsive tokens in a second :root block.
No existing class or token is renamed or removed; 126 tests green; build clean.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Responsive shell — desktop sidebar vs mobile bottom-nav + fluid content layout

**Files:**
- Modify: `frontend/src/components/AppShell.tsx` (nav rendering + content wrapper)
- Modify: `frontend/src/styles.css` (new `.app-sidebar` + desktop layout breakpoints; extend `min-width:960px`)

**Scene:** AppShell currently always renders `<nav className="bottom-nav">` with 8 `TabButton`s. On a wide desktop the `.app` is a 560–720px centered column above a full-width bottom bar — wasted space. This task makes the shell responsive: on `≥1024px` a left **sidebar** replaces the bottom-nav (only one mounted at a time via `useIsDesktop()`), and the content area becomes a fluid multi-column-friendly region with a reading max-width.

- [ ] **Step 1: Wire `useIsDesktop` + a `DesktopNav` into AppShell**

At the top of `AppShell.tsx`, add the import and a `DesktopNav` component. The `DesktopNav` reuses the **same** `TabButton` component and the **same** glyphs/labels — only the wrapper changes (`<aside class="app-sidebar">` + a brand mark) — so the 8 tab buttons keep byte-identical accessible names. Because `useIsDesktop()` is `false` in jsdom, tests render the existing `.bottom-nav` branch unchanged.

Add to imports:
```ts
import { useIsDesktop } from "../lib/useIsDesktop";
```

Inside `AppShell`, after `const [unread, setUnread] = useState(0);` add:
```ts
  const isDesktop = useIsDesktop();
```

Replace the `<nav className="bottom-nav" aria-label="Primary"> … </nav>` block (the 8 `TabButton`s) with:

```tsx
      {isDesktop ? (
        <DesktopNav
          view={view}
          selectedCard={!!selectedCard}
          unread={unread}
          onSelect={selectTab}
        />
      ) : (
        <nav className="bottom-nav" aria-label="Primary">
          <TabButton label="Scan" active={view === "scan" && !selectedCard} onClick={() => selectTab("scan")} glyph={<ScanGlyph />} />
          <TabButton label="Vault" active={view === "vault" && !selectedCard} onClick={() => selectTab("vault")} glyph={<VaultGlyph />} />
          <TabButton label="Alerts" active={view === "alerts" && !selectedCard} onClick={() => selectTab("alerts")} glyph={<BellGlyph />} badge={unread} />
          <TabButton label="Deals" active={view === "deals" && !selectedCard} onClick={() => selectTab("deals")} glyph={<TagGlyph />} />
          <TabButton label="Sealed" active={view === "sealed" && !selectedCard} onClick={() => selectTab("sealed")} glyph={<BoxGlyph />} />
          <TabButton label="Ledger" active={view === "ledger" && !selectedCard} onClick={() => selectTab("ledger")} glyph={<LedgerGlyph />} />
          <TabButton label="Browse" active={view === "browse" && !selectedCard} onClick={() => selectTab("browse")} glyph={<SearchGlyph />} />
          <TabButton label="More" active={view === "more" && !selectedCard} onClick={() => selectTab("more")} glyph={<MoreGlyph />} />
        </nav>
      )}
```

Add the `DesktopNav` component above `TabButton` (it is a presentational shell around the same `TabButton`):

```tsx
// Desktop sidebar nav — the ≥1024px replacement for the mobile bottom-nav. Only one
// of the two is ever mounted (useIsDesktop decides), so getByRole("button",{name:"Scan"})
// still resolves to a single element in tests (jsdom → mobile → bottom-nav). Reuses the
// existing TabButton + glyphs verbatim so accessible names are byte-identical.
function DesktopNav({
  view,
  selectedCard,
  unread,
  onSelect,
}: {
  view: TabView;
  selectedCard: boolean;
  unread: number;
  onSelect: (tab: TabView) => void;
}) {
  return (
    <aside className="app-sidebar" aria-label="Primary">
      <div className="app-sidebar-brand">
        <span className="app-sidebar-mark" aria-hidden="true">✦</span>
        <span className="app-sidebar-title">Card Scan</span>
      </div>
      <nav className="app-sidebar-nav">
        <TabButton label="Scan" active={view === "scan" && !selectedCard} onClick={() => onSelect("scan")} glyph={<ScanGlyph />} badge={undefined} />
        <TabButton label="Vault" active={view === "vault" && !selectedCard} onClick={() => onSelect("vault")} glyph={<VaultGlyph />} />
        <TabButton label="Alerts" active={view === "alerts" && !selectedCard} onClick={() => onSelect("alerts")} glyph={<BellGlyph />} badge={unread} />
        <TabButton label="Deals" active={view === "deals" && !selectedCard} onClick={() => onSelect("deals")} glyph={<TagGlyph />} />
        <TabButton label="Sealed" active={view === "sealed" && !selectedCard} onClick={() => onSelect("sealed")} glyph={<BoxGlyph />} />
        <TabButton label="Ledger" active={view === "ledger" && !selectedCard} onClick={() => onSelect("ledger")} glyph={<LedgerGlyph />} />
        <TabButton label="Browse" active={view === "browse" && !selectedCard} onClick={() => onSelect("browse")} glyph={<SearchGlyph />} />
        <TabButton label="More" active={view === "more" && !selectedCard} onClick={() => onSelect("more")} glyph={<MoreGlyph />} />
      </nav>
    </aside>
  );
}
```

> The `TabButton` `badge` prop is already optional (`badge?: number`); passing `undefined` explicitly is fine. The bottom-nav branch passes `badge={unread}` only to Alerts as before — copy the **exact** existing prop pattern from the original block (the implementer must match the original 8 `TabButton` lines byte-for-byte except wrapping them in the `isDesktop ?` ternary; do not "tidy" them).

- [ ] **Step 2: Add the `.app-sidebar` + desktop layout CSS**

Append to the trailing UI-overhaul block in `styles.css`:

```css
/* Desktop sidebar nav (≥1024px). Hidden on mobile; the bottom-nav is hidden on
   desktop — the two are never both visible (and never both mounted, via JS). */
.app-sidebar {
  display: none;
  position: fixed;
  inset: 0 auto 0 0;
  width: var(--sidebar-w);
  padding: 24px 16px;
  gap: 18px;
  flex-direction: column;
  background: var(--glass-bg-strong);
  border-right: 1px solid var(--glass-border);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  z-index: 20;
}
.app-sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 14px;
  border-bottom: 1px solid var(--line);
}
.app-sidebar-mark {
  font-size: 20px;
  background: var(--grad-accent);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.app-sidebar-title {
  font-weight: 650;
  letter-spacing: 0.01em;
  color: var(--fg);
}
.app-sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
/* Sidebar TabButtons render stacked; override the mobile bottom-nav button layout
   for this context only. These are additive — the existing .bottom-nav button
   rules are untouched. */
.app-sidebar .app-sidebar-nav button {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  min-height: 44px;
  border-radius: var(--r-2);
  color: var(--fg-dim);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background var(--t-fast) ease, color var(--t-fast) ease;
}
.app-sidebar .app-sidebar-nav button:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--fg);
}
.app-sidebar .app-sidebar-nav button[aria-current="true"] {
  background: var(--grad-accent-soft);
  color: var(--fg);
  box-shadow: inset 0 0 0 1px var(--glass-border);
}
.app-sidebar .nav-glyph {
  width: 22px;
  height: 22px;
}
.app-sidebar .nav-glyph-wrap {
  position: relative;
  display: inline-flex;
}
.app-sidebar .nav-badge {
  position: absolute;
  top: -6px;
  right: -10px;
}

@media (min-width: 1024px) {
  /* Sidebar appears; bottom-nav hidden; app becomes a grid with the sidebar column. */
  .bottom-nav { display: none !important; }
  .app.app-shell {
    max-width: none;
    margin: 0;
    padding: 0 0 0 var(--sidebar-w);
    min-height: 100dvh;
    display: block;
  }
  .app-shell .persistent-header {
    position: sticky;
    top: 0;
    margin-left: 0;
    padding: 18px var(--content-pad);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border-bottom: 1px solid var(--glass-border);
  }
  .app-shell .app-content {
    max-width: var(--content-max);
    margin: 0 auto;
    padding: var(--content-pad);
    padding-bottom: 64px;
    width: 100%;
  }
  .app-sidebar { display: flex; }
}

@media (min-width: 1440px) {
  :root { --sidebar-w: 264px; --content-max: 1320px; }
}
```

- [ ] **Step 3: Make the mobile shell page background use the gradient (additive, mobile + desktop)**

Append (applies to the existing `.app` on all sizes; the desktop block above overrides the layout but this paints the gradient behind everything):

```css
/* Page gradient backdrop — additive behind the existing .app. */
body {
  background: var(--bg);
  background-image: var(--grad-page);
  background-attachment: fixed;
  min-height: 100dvh;
}
```

- [ ] **Step 4: Verify tests stay green — the critical check**

Run: `npm --prefix frontend test -- --run`
Expected: 126 pass. **BulkScan must still find exactly one "Scan" button** — this is the key invariant. If any test fails with "found multiple elements", the cause is both navs being mounted; fix by ensuring `useIsDesktop()` returns `false` in jsdom (it does — `window.matchMedia` returns `matches:false`). Do NOT add a `matchMedia` polyfill to the test setup.

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd C:/ClaudeKnowledge && git add frontend/src/components/AppShell.tsx frontend/src/styles.css
git commit -m "$(cat <<'EOF'
feat(ui): responsive shell — desktop sidebar nav (>=1024px) + fluid content

AppShell now renders EITHER a desktop sidebar (>=1024px) OR the mobile bottom-nav
via useIsDesktop() — never both, so getByRole("button",{name:"Scan"}) still resolves
to a single element (jsdom has no viewport -> mobile -> bottom-nav; 126 tests green).
The sidebar reuses the existing TabButton + glyphs verbatim, so accessible names are
byte-identical. Desktop: sidebar pinned left, content max-width 1180px centered with
clamp padding, bottom-nav hidden. Adds a gradient page backdrop and glass header on
desktop. No existing class/role/text renamed.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Motion in the shell — view transitions (AnimatePresence) + WatchCardSheet spring + overlay fade

**Files:**
- Modify: `frontend/src/components/AppShell.tsx` (wrap view branch in AnimatePresence + PageTransition; fade the watch-sheet overlay)
- Modify: `frontend/src/components/WatchCardSheet.tsx` (sheet + overlay become motion.div with spring)

**Scene:** Tab switches and the CardDetail overlay currently swap instantly. This task adds a polished fade+slide on view changes and a spring sheet entrance/exit, gated by reduced-motion. DOM structure, roles, `aria-label`, `aria-modal`, all `input[name]`, and button text are untouched — motion wraps the existing elements.

- [ ] **Step 1: Wrap the AppShell view branch in AnimatePresence + PageTransition**

In `AppShell.tsx`, add imports:
```ts
import { AnimatePresence } from "framer-motion";
import { PageTransition } from "./motion";
```

Replace the `<div className="app-content"> … </div>` render branch so each branch is wrapped in `<PageTransition id="…">`. The `key`/`id` drives the transition; use the view id (or `"card"` for the selectedCard overlay):

```tsx
      <div className="app-content">
        <AnimatePresence mode="wait">
          {selectedCard ? (
            <PageTransition id="card">
              <CardDetail
                cardId={selectedCard.cardId}
                variant={selectedCard.variant}
                onBack={() => setSelectedCard(null)}
                onWatchCard={(c) => openWatchSheet(c)}
              />
            </PageTransition>
          ) : view === "scan" ? (
            <PageTransition id="scan">
              <ScanPane scan={scan} onViewCard={(cardId) => setSelectedCard({ cardId })} onWatchCard={(card) => openWatchSheet(card)} />
            </PageTransition>
          ) : view === "vault" ? (
            <PageTransition id="vault"><PortfolioView /></PageTransition>
          ) : view === "alerts" ? (
            <PageTransition id="alerts">
              <AlertsFeed onOpenCard={(c) => setSelectedCard(c)} onWatchCard={(c) => openWatchSheet(c)} />
            </PageTransition>
          ) : view === "deals" ? (
            <PageTransition id="deals"><Deals onOpenCard={(c) => setSelectedCard(c)} /></PageTransition>
          ) : view === "ledger" ? (
            <PageTransition id="ledger"><SealedLedger /></PageTransition>
          ) : view === "sealed" ? (
            <PageTransition id="sealed"><SealedDeals /></PageTransition>
          ) : view === "browse" ? (
            <PageTransition id="browse"><Browse onSelectCard={(c) => setSelectedCard(c)} /></PageTransition>
          ) : (
            <PageTransition id="more"><More /></PageTransition>
          )}
        </AnimatePresence>
      </div>
```

> Preserve the **exact** prop wiring of each component from the original (do not drop `onViewCard`/`onOpenCard`/`onWatchCard` callbacks). The only change is wrapping each branch in `<PageTransition id="…">` and the surrounding `<AnimatePresence mode="wait">`.

- [ ] **Step 2: Make the WatchCardSheet sheet + overlay animate (spring entrance, fade exit)**

In `WatchCardSheet.tsx`, add imports:
```ts
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
```

The component currently returns `<div className="sheet-overlay"> … <div className="sheet" role="dialog" …> … </div> </div>` (conditionally rendered by the parent via `{watchSheet.open && <WatchCardSheet …/>}`). To get an exit animation, the parent must keep it mounted during exit. Two options:

**Option A (simpler, recommended):** keep the parent's `{watchSheet.open && …}` gate as-is (no exit animation, just entrance), and animate the overlay/sheet on mount only. Change the overlay + sheet to `motion.div`:

```tsx
  const reduced = useReducedMotion();
  return (
    <div className="sheet-overlay" /* keep the existing className/onClick (overlay click closes) */ >
      <motion.div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Watch a card"
        initial={reduced ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.98 }}
        animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
        transition={reduced ? { duration: 0.15 } : { type: "spring", stiffness: 320, damping: 30, mass: 0.9 }}
        /* keep the existing onClick stopPropagation on the sheet so overlay-click doesn't close */
      >
        {/* …existing sheet internals unchanged… */}
      </motion.div>
    </div>
  );
```

And give the overlay a fade-in:
```tsx
    <motion.div
      className="sheet-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.16 }}
      /* existing overlay onClick={onClose} stays */
    >
```

> **The implementer must preserve every existing prop/attribute on `.sheet-overlay` and `.sheet`** — `onClick` (overlay closes, sheet stops propagation), `role="dialog"`, `aria-modal="true"`, `aria-label="Watch a card"`, `.sheet-handle`, `.sheet-head`/`.sheet-close` (`aria-label="Close"`), every `input[name=…]`, the `.watch-type-chip` buttons with `aria-pressed`, and the submit button text (`/^watch$/i`, `"Watching…"`). Motion is layered on the same elements; no class is renamed.

- [ ] **Step 3: Verify tests stay green**

Run: `npm --prefix frontend test -- --run`
Expected: 126 pass. WatchCardSheet tests assert `.watch-type-chip`, `input[name="target_price"]`, `/^watch$/i`, the `role="dialog"` + `aria-label="Watch a card"`, `aria-label="Close"` — all preserved. If a test fails because `motion.div` changes an attribute the test queries, re-add that attribute verbatim on the `motion.div` (motion passes through arbitrary props).

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd C:/ClaudeKnowledge && git add frontend/src/components/AppShell.tsx frontend/src/components/WatchCardSheet.tsx
git commit -m "$(cat <<'EOF'
feat(ui): polished motion — view fade+slide transitions + sheet spring

Wraps each AppShell view branch in <AnimatePresence mode="wait"> + <PageTransition>
keyed by view id (and "card" for the CardDetail overlay) for a fade+slide on tab
switches. WatchCardSheet's overlay + sheet become motion.div with a spring entrance
(reduced-motion: opacity-only). All roles, aria-labels, input[name]s, and button text
preserved — motion is layered on the existing elements. 126 tests green.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Refined dark-glass surfaces + gradient accents (CSS design refresh)

**Files:**
- Modify: `frontend/src/styles.css` (layer glass + gradient on existing card/surface classes; new utility classes; do NOT rename/remove existing rules)

**Scene:** The surfaces are currently flat `--surface` cards on `--bg`. This task elevates them to the refined dark-glass identity: cards get `--glass-bg` + `backdrop-filter` + a hairline `--glass-border` + a subtle top highlight gradient; primary buttons + active chips get the `--grad-accent` fill; the accent surfaces (`.valuation .up`, `.deal-chip.rip/.flip`) get gradient treatments. All additive — existing flat backgrounds remain as the no-backdrop-filter fallback.

- [ ] **Step 1: Glass + gradient surface layer (additive, appended to the UI-overhaul block)**

```css
/* === Glass + gradient surface elevation (additive on existing card classes) === */

/* Card-like surfaces: deal cards, alert rows, browse results, bulk cells, channel
   cards, watchlist rows, the camera frame, the scan result, the sheet. Each keeps
   its existing --surface background as the fallback; the glass layer sits on top
   via a second background + border + blur. */
.deal-card,
.alert-row,
.browse-result,
.bulk-cell,
.channel-card,
.watchlist-row,
.result,
.camera-frame,
.sheet,
.portfolio-table-wrap,
.grading-upside,
.centering,
.sold-comps,
.card-detail {
  background-color: var(--glass-bg);
  background-image: var(--grad-surface);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-3);
  box-shadow: var(--shadow-glass);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}

/* Hover affordance on interactive card rows — additive transition; the motion
   library handles the lift in list components, this is the CSS colour shift. */
.alert-row:hover,
.browse-result:hover,
.deal-card:hover,
.watchlist-row:hover,
.channel-card:hover {
  border-color: rgba(255, 203, 5, 0.22);
  background-image: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0));
}

/* Primary buttons + active CTAs get the yellow gradient fill. The existing
   .primary color stays as fallback for no-backdrop contexts. */
.primary,
.sealed-deals-btn,
.bulk-add-all,
.watch-card-btn {
  background-image: var(--grad-accent);
  border: none;
  color: #1a1500;
  font-weight: 650;
  box-shadow: 0 6px 20px rgba(255, 203, 5, 0.18);
  transition: transform var(--t-fast) ease, box-shadow var(--t-fast) ease, filter var(--t-fast) ease;
}
.primary:hover,
.sealed-deals-btn:hover,
.bulk-add-all:hover,
.watch-card-btn:hover {
  filter: brightness(1.05);
  box-shadow: 0 10px 28px rgba(255, 203, 5, 0.26);
}
.primary:active,
.sealed-deals-btn:active,
.bulk-add-all:active,
.watch-card-btn:active {
  transform: translateY(1px) scale(0.99);
}

/* Accent chips — RIP/flip and up/down pills get gradient + glow. Existing
   --accent/--ok/--down colors remain as the fallback colour. */
.deal-chip.rip {
  background-image: linear-gradient(135deg, rgba(255,203,5,0.20), rgba(255,203,5,0.08));
  border: 1px solid rgba(255, 203, 5, 0.35);
  color: var(--accent);
}
.deal-chip.flip {
  background-image: linear-gradient(135deg, rgba(59,109,240,0.22), rgba(59,109,240,0.08));
  border: 1px solid rgba(59, 109, 240, 0.4);
  color: #8fb0ff;
}
.valuation .up { color: #4ade80; }
.valuation .unknown { color: var(--fg-faint); }
.ledger-profit.pos { color: #4ade80; }
.ledger-profit.neg { color: var(--down); }

/* Header title gets a subtle gradient text on desktop (additive). */
@media (min-width: 1024px) {
  .app-shell .app-header h1 {
    background: linear-gradient(90deg, var(--fg), var(--fg-dim));
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }
}

/* Inputs/search fields get a glass inset. Additive — keeps existing .deals-search /
   .browse-input / .ledger-input / .watch-field backgrounds as fallback. */
.deals-search,
.browse-input,
.ledger-input,
.watch-field input,
.edit-price,
.grading-label-form input,
.grading-label-form select,
.paid input {
  background-color: rgba(0, 0, 0, 0.28);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-2);
  transition: border-color var(--t-fast) ease, box-shadow var(--t-fast) ease;
}
.deals-search:focus,
.browse-input:focus,
.ledger-input:focus,
.watch-field input:focus,
.edit-price:focus {
  border-color: rgba(255, 203, 5, 0.4);
  box-shadow: 0 0 0 3px rgba(255, 203, 5, 0.12);
  outline: none;
}

/* Reduced motion: nothing here animates transforms, but keep the hover colour shift
   instant for reduced-motion users. */
@media (prefers-reduced-motion: reduce) {
  .primary, .sealed-deals-btn, .bulk-add-all, .watch-card-btn,
  .alert-row, .browse-result, .deal-card, .watchlist-row, .channel-card {
    transition: none;
  }
}
```

- [ ] **Step 2: Verify tests + build**

Run: `npm --prefix frontend test -- --run`
Expected: 126 pass (CSS-only; tests don't assert styles).

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd C:/ClaudeKnowledge && git add frontend/src/styles.css
git commit -m "$(cat <<'EOF'
feat(ui): refined dark-glass surfaces + gradient accents

Layers glass (backdrop-filter + hairline border + top highlight gradient) on the
existing card/surface classes — deal cards, alert rows, browse results, bulk cells,
channel cards, watchlist rows, camera frame, scan result, sheet, portfolio table,
grading/centering/sold-comps panels, card detail. Primary CTAs get the yellow
gradient fill + glow; RIP/flip chips and up/down pills get gradient treatments;
inputs get glass insets + focus rings. All additive — existing flat backgrounds
remain as fallback, no class renamed. 126 tests green.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: List-surface stagger + hover/tap micro-interactions + desktop multi-column grids

**Files:**
- Modify: `frontend/src/components/AlertsFeed.tsx`, `Deals.tsx`, `Browse.tsx`, `SealedDeals.tsx`, `SealedLedger.tsx`, `PortfolioView.tsx` (wrap list items in `StaggerItem`/`MotionCard`)
- Modify: `frontend/src/styles.css` (desktop multi-column grids for the list surfaces)

**Scene:** Lists currently render flat `.alert-row`/`.deal-card`/`.browse-result`/`.holding-row` items that pop in at once. This task (a) staggers their mount via `StaggerList`/`StaggerItem`, (b) adds hover-lift/tap-scale via `MotionCard` on the card-like items, and (c) on desktop lays the grids out in multiple columns so wide screens use the space. **No class name, text, `aria-label`, or `input[name]` changes.**

- [ ] **Step 1: Wrap list items in StaggerItem + MotionCard (per component)**

For each component below, the pattern is: wrap the list `<ul>` in `<StaggerList>` and each `<li>`'s inner card in `<StaggerItem>` (and the interactive card element in `<MotionCard as="button"|"div">`). **Keep the existing `<ul class="…">`, `<li>`, and inner class names exactly.** `StaggerList` uses `display:contents` so it does not add a layout box; `StaggerItem` renders a `<div>` wrapper — put it *inside* the `<li>` wrapping the card, so the `<li>`/`<ul>` semantics and the existing `.deal-list`/`.alert-list`/`.browse-results` grid containers are untouched.

- [ ] **Step 1a — AlertsFeed.tsx:** wrap `<ul className="alert-list">` in `<StaggerList>`; each `.alert-row` button → `<MotionCard as="button" className="alert-row …">` (move the existing `className`, `onClick`, `aria-` props onto `MotionCard`; it renders a `<button>` so `getByRole("button")` still resolves and `.alert-row`/`.alert-row.unread` classList assertions hold). Preserve the `.alert-icon`/`.alert-body`/`.alert-message`/`.alert-meta` children verbatim.

- [ ] **Step 1b — Deals.tsx:** wrap `<ul className="deal-list">` in `<StaggerList>`; each `DealCard`'s `.deal-card` → `<MotionCard as="div" className="deal-card">`. Keep `.deal-card-head`/`.deal-title`/`.deal-price`/`.deal-row.deal-rip`/`.deal-row.deal-flip`/`.deal-chip.rip`/`.deal-chip.flip`/`.deal-rip-edge`/`.deal-flip-10`/`.deal-flip-9`/`.deal-caveat` unchanged.

- [ ] **Step 1c — Browse.tsx:** wrap `<ul className="browse-results">` in `<StaggerList>`; each `.browse-result` button → `<MotionCard as="button" className="browse-result">` (preserve `onClick`, `.browse-thumb` img, `.browse-result-text`).

- [ ] **Step 1d — SealedDeals.tsx:** same pattern as Deals — `.deal-list` → `<StaggerList>`, each `SealedDealCard` `.deal-card` → `<MotionCard as="div" className="deal-card">`.

- [ ] **Step 1e — SealedLedger.tsx:** `.deal-list` → `<StaggerList>`; each `.deal-card` → `<MotionCard as="div" className="deal-card">`. Preserve `.ledger-profit.pos/.neg`, `.ledger-delete` (its `/delete/i` text + `aria-` and the DELETE callback), and the `.ledger-form` inputs (`name="ledger-query"` etc. — untouched).

- [ ] **Step 1f — PortfolioView.tsx:** the rows are `<tr class="holding-row">` inside `.portfolio-table`. Staggering table rows is fragile (motion wraps in a `<div>` which can't be a `<tr>` child). **Do NOT wrap table rows in StaggerItem.** Instead, give the `.holding-row` a hover lift via CSS only (add a `.portfolio-table .holding-row:hover { background: …; }` rule in Step 2). The valuation cards (`.valuation` grid cells) can be wrapped in `<StaggerItem>` since they're `<div>`s — wrap each `.valuation` cell. Preserve the 8 `td[data-label]` cells and `/history/i` button.

> If wrapping any element in `MotionCard as="button"` causes a test that does `container.querySelector(".alert-row")` to fail because the class moved onto a `motion.button` (which still renders `<button class="alert-row">`), the query still holds — `motion.button` is a `<button>`. Verify with the test run after each component edit; if a test breaks, the cause is almost certainly a dropped prop/attribute, not the motion wrapper — re-add it.

- [ ] **Step 2: Desktop multi-column grids for the list surfaces (additive CSS)**

Append to the UI-overhaul block:

```css
/* === Desktop multi-column grids for list surfaces (>=1024px) === */
@media (min-width: 1024px) {
  /* Deal / sealed / ledger cards: 2 columns; 3 at very wide. */
  .deal-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .deal-list .deal-card { margin: 0; }
  /* Browse results: responsive auto-fill thumbs. */
  .browse-results {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  /* Alerts feed: 2-column list. */
  .alert-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  /* Portfolio: keep the real table but widen; the stacked-card mobile layout
     (max-width:639px block at L760) is untouched. */
  .portfolio-table-wrap {
    border-radius: var(--r-3);
    overflow: hidden;
  }
  .portfolio-table .holding-row:hover {
    background: rgba(255, 255, 255, 0.03);
  }
  /* Valuation grid: 4 columns on desktop (the existing min-width:960px block
     already does 4; this reinforces with the glass card styling). */
  .valuation {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
  }
}
@media (min-width: 1440px) {
  .deal-list { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .alert-list { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .browse-results { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
}

/* Mobile: ensure list <ul>s still lay out as a single column (the grids above
   only apply >=1024px; existing block styles handle <1024px). */
```

- [ ] **Step 3: Verify tests + build**

Run: `npm --prefix frontend test -- --run`
Expected: 126 pass. Pay attention to: AlertsFeed (`.alert-row`, `.alert-row.unread`, `/watch a card/i`, `/radar/i`), Deals (`.deal-card`, `.deal-chip.rip/.flip`, `.deal-rip-edge`, `.deal-flip-10`, `.deal-flip-9`), Browse (`.browse-result`), SealedDeals (`.deal-card`, `.deal-chip.flip`), SealedLedger (`.deal-card`, `.ledger-delete`, `/refresh/i`, `/log purchase/i`, `/sync to google/i`), PortfolioView (`.holding-row`, 8 `td[data-label]`, `/history/i`).

Run: `npm --prefix frontend run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd C:/ClaudeKnowledge && git add frontend/src/components frontend/src/styles.css
git commit -m "$(cat <<'EOF'
feat(ui): list stagger + hover/tap micro-interactions + desktop multi-column grids

Wraps the list surfaces (alerts, deals, browse, sealed, ledger) in StaggerList/
StaggerItem for mount stagger and MotionCard for hover-lift/tap-scale on the card
items — layered on existing elements so all class names, text, aria-labels, and
input names are preserved. PortfolioView table rows get a CSS hover (motion can't
wrap a <tr>). Desktop >=1024px lays the deal/alert/browse lists in 2-3 column
grids and widens the portfolio table; the mobile stacked-card layout is untouched.
126 tests green; build clean.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Verify, commit, push, Pages, docs + memory

**Files:**
- Verify-only: full frontend test suite + build + (frontend-only) 105-scan baseline untouched
- Modify: repo `AI_CONTEXT.md` + `PROJECT.md` (UI-overhaul note)
- Modify (controller, not an implementer): `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md` + `MEMORY.md`

**Scene:** Final gate. Confirm the 126 tests are green, the build is clean, the 105-scan baseline is untouched (frontend-only phase → it is untouched by construction, but state it), push to `origin/main`, kick a Pages rebuild, and record the phase.

- [ ] **Step 1: Full verification**

Run: `npm --prefix frontend test -- --run`
Expected: 126 pass.

Run: `npm --prefix frontend run build`
Expected: `tsc -b` + `vite build` clean; `dist/` produced.

Sanity (frontend-only baseline statement — no backend run needed): confirm no file under `backend/` or `data/` was modified this phase:
Run: `cd C:/ClaudeKnowledge && git diff --name-only origin/main -- backend data`
Expected: empty (nothing changed under backend/ or data/ relative to origin/main).

- [ ] **Step 2: Update docs**

Append to `AI_CONTEXT.md` (repo root) a short UI-overhaul section noting: refined dark-glass identity, responsive sidebar (≥1024px) + mobile bottom-nav, Framer Motion view transitions + sheet spring + stagger + hover/tap, 126 frontend tests green, frontend-only (backend/568 + 105-scan baseline untouched). Update the test-count line if AI_CONTEXT tracks it.

Update `PROJECT.md` status/next-step line.

- [ ] **Step 3: Commit docs + push**

```bash
cd C:/ClaudeKnowledge && git add AI_CONTEXT.md PROJECT.md
git commit -m "$(cat <<'EOF'
docs: record responsive UI overhaul (refined dark + polished motion)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 4: GitHub Pages rebuild + status**

```bash
gh api -X POST repos/Lucas-Bianco/pokemon-card-platform/pages/builds
# then poll until status is "built" not "errored":
gh api repos/Lucas-Bianco/pokemon-card-platform/pages/builds --jq '.[0] | {status: .status, created_at: .created_at}'
```
Expected: eventually `status: "built"`. If `errored`, inspect the build log; the most likely cause is an asset path or a `tsc`/`vite build` issue that Step 1 would have caught — fix and re-push.

- [ ] **Step 5: Memory update (controller does this directly, not via a subagent)**

Update `C:\Users\Lucas\.claude\projects\C--Users-Lucas\memory\pokemon-card-platform-project.md` — record a UI-overhaul phase paragraph (date 2026-08-20): refined dark-glass identity, responsive desktop sidebar (`useIsDesktop`, ≥1024px) + mobile bottom-nav (only one mounted → `getByRole("button",{name:"Scan"})` still single), Framer Motion 12 (PageTransition view fade+slide, StaggerList/Item, MotionCard hover/tap, WatchCardSheet spring — all `useReducedMotion`-gated), desktop multi-column grids, all 126 tests green + 568 backend untouched + 105-scan baseline 0 regressions, Pages built. Note the do-not-break contract held. Update the `MEMORY.md` hook line.

---

## Self-review notes (read after writing, not a task)

- **Spec coverage:** "fully custom impressive UI" → glass + gradients (T4) + custom sidebar (T2). "forms to any screen size, mobile or desktop" → responsive shell (T2) + multi-column grids (T5) + `1440px` tier (T2). "add animations, make it the best" → Framer Motion view transitions (T3) + stagger + hover/tap (T5) + sheet spring (T3). ✓
- **Do-not-break contract:** every frozen class/name/label/data-label is preserved by construction (motion wraps, never renames; CSS is additive). The one structural change (sidebar vs bottom-nav) is JS-gated so only one nav is mounted. ✓
- **Type consistency:** `useIsDesktop()` returns `boolean`; `PageTransition({id, children})`; `StaggerList({children})`; `StaggerItem({children, className?})`; `MotionCard({as?, className?, children, ...rest})`. `DesktopNav` props `{view, selectedCard, unread, onSelect}` match the call site. ✓
- **No placeholders:** every step has real code or a real command. ✓
- **Risk to watch in execution:** (1) framer-motion under jsdom — `useReducedMotion()` is `false` in jsdom so transitions render; if any test flakes on an `act()` warning or a motion-measurement, the fix is to ensure the motion wrapper doesn't change DOM structure (it doesn't) and that no `useEffect` in motion triggers an async state update the test doesn't await. (2) `MotionCard as="button"` must receive the existing `onClick`/`aria-` props via `...rest` — the implementer must move them onto the component. (3) PortfolioView rows are NOT motion-wrapped (table-row constraint) — CSS hover only. (4) `git diff --name-only origin/main -- backend data` in T6 assumes `origin/main` is up to date locally; if not, `git fetch origin` first.