import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";

import { useIsDesktop } from "../lib/useIsDesktop";
import { useRoute } from "../lib/useRoute";
import { KEY_TAB_VIEWS, type TabView } from "../lib/route";
import type { AppMode } from "../lib/appMode";
import { getUnreadCount } from "../api/client";
import type { RecognizeResponse } from "../api/types";
import AlertsFeed from "./AlertsFeed";
import Binder from "./Binder";
import Wants from "./Wants";
import CameraCapture from "./CameraCapture";
import CardDetail from "./CardDetail";
import CornerAdjust from "./CornerAdjust";
import Browse from "./Browse";
import Dashboard from "./Dashboard";
import Deals from "./Deals";
import More from "./More";
import PortfolioView from "./PortfolioView";
import PriceLookup from "./PriceLookup";
import ScanResult from "./ScanResult";
import SealedCatalog from "./SealedCatalog";
import SetDetail from "./SetDetail";
import Sets from "./Sets";
import SealedDeals from "./SealedDeals";
import SealedLedger from "./SealedLedger";
import ShopAssistant from "./ShopAssistant";
import WatchCardSheet from "./WatchCardSheet";
import { PageTransition } from "./motion";
import { CommandPalette } from "./CommandPalette";
import { useToast } from "./Toast";

// The scan flow stays owned by App (which holds the recognition state and the
// scan-log callbacks); AppShell receives it as a bundle so it can render the
// Scan tab without knowing the recognition mechanics.
export interface BulkFlow {
  results: RecognizeResponse[];
  batchId: string | null;
  scanIds: (number | null)[];
  variants: string[];
  logStatus: ("saved" | "failed" | null)[];
  busy: boolean;
  error: string | null;
  note: string | null;
  variantOptions: string[];
  onCapture: (image: Blob) => void;
  onConfirm: (i: number, acquiredPrice: number | null) => void;
  onPick: (i: number, cardId: string, acquiredPrice: number | null) => void;
  onReject: (i: number) => void;
  onRescan: (i: number) => void;
  onVariantChange: (i: number, variant: string) => void;
  onAddAll: () => void;
}

export interface ScanFlow {
  result: RecognizeResponse | null;
  variant: string;
  scanId: number | null;
  busy: boolean;
  error: string | null;
  note: string | null;
  adjusting: boolean;
  lastImage: Blob | null;
  canAdjust: boolean;
  onCapture: (image: Blob) => void;
  onCorners: (corners: [number, number][]) => void;
  onConfirm: (acquiredPrice: number | null) => void;
  onPick: (cardId: string, acquiredPrice: number | null) => void;
  onReject: () => void;
  onRescan: () => void;
  onAdjust: () => void;
  onCancelAdjust: () => void;
  // Phase 4 bulk mode (additive). `mode` defaults to "single"; `bulk` is null
  // unless the user has toggled into bulk, so the single-card path is untouched.
  mode: "single" | "bulk";
  onToggleMode: (mode: "single" | "bulk") => void;
  bulk: BulkFlow | null;
}

interface Props {
  scan: ScanFlow;
  appMode: AppMode;
  onAppModeChange: (mode: AppMode) => void;
}

// A single nav entry: which tab it opens, its label, its glyph, and whether it
// carries the unread-alert badge. The nav is now config-driven (one array for
// full mode, the key subset for key mode) so the bottom-nav and the desktop
// sidebar render from the same source and the do-not-break "exactly one button
// per label" invariant holds in both modes — only one nav is ever mounted.
export interface NavItem {
  view: TabView;
  label: string;
  glyph: React.ReactNode;
  badge?: "unread";
}

const TAB_TITLES: Record<TabView, string> = {
  home: "Home",
  scan: "Scan",
  vault: "Vault",
  binder: "Binder",
  wants: "Wants",
  alerts: "Alerts",
  deals: "Deals",
  prices: "Prices",
  ledger: "Ledger",
  sealed: "Sealed",
  catalog: "Catalog",
  browse: "Browse",
  sets: "Sets",
  shop: "Shop",
  more: "More",
};

// Five-tab shell: Alerts-first (the alert feed is the landing surface — T7 ships
// the live feed; T6 lands the tab + an honest empty-state placeholder). The
// bottom nav is always visible now that there are 5 surfaces — the prior
// in-browser header toggle did not scale beyond two tabs. A slim header carries
// the active title. CardDetail renders as a transient detail view over the
// current tab; back returns to it.
export default function AppShell({ scan, appMode, onAppModeChange }: Props) {
  const { toast } = useToast();
  // The tab, the open set and the open card live in the URL rather than in
  // component state, so a reload lands back where the user was, a link can
  // point at a specific tab/card/set, and the manifest's `?view=` home-screen
  // shortcuts resolve. See lib/route.ts for the scheme.
  const { route, navigate, back } = useRoute();
  const { view, set: selectedSet, card: selectedCard } = route;
  const [unread, setUnread] = useState(0);
  const isDesktop = useIsDesktop();
  // The WatchCardSheet is app-level so any surface (AlertsFeed empty-state
  // CTA, CardDetail "Watch this card", the scan onboarding nudge) can open it
  // preselected to a card. `card` is undefined for the no-preselect CTA.
  const [watchSheet, setWatchSheet] = useState<{
    open: boolean;
    cardId?: string;
    variant?: string;
  }>({ open: false });
  const [paletteOpen, setPaletteOpen] = useState(false);

  function openWatchSheet(card?: { cardId?: string; variant?: string }) {
    setWatchSheet({ open: true, cardId: card?.cardId, variant: card?.variant });
  }
  function closeWatchSheet() {
    setWatchSheet((prev) => ({ ...prev, open: false }));
  }

  function refreshUnread() {
    getUnreadCount()
      .then(setUnread)
      .catch(() => setUnread(0));
  }

  // Unread badge for the Alerts tab. Fetched on mount; refreshed when a watch
  // is created (the sheet's onCreated) so the badge reflects new activity. A
  // failed count is honest zero (no fake badge), not an error.
  useEffect(() => {
    refreshUnread();
  }, []);

  // Key-mode landing: a fresh load with no `?view=` lands on Scan, not Home —
  // Home/Dashboard is a non-key surface tucked under More in key mode, so the
  // curated first screen is the collector's entry point (capture a card). Only
  // the bare no-view landing redirects; an explicit `?view=home` (or any non-key
  // view reached via the command palette) still renders that surface, just with
  // the More tab highlighted — non-key surfaces stay reachable, never hidden.
  //
  // The raw initial URL is captured during render (before effects), because the
  // useRoute mount effect canonicalises `?view=home` → "" (home omits the view
  // param) before this effect runs — reading location.search here would make an
  // explicit home deep-link look identical to a bare "/" and wrongly redirect it.
  const initialSearch = useRef<string | null>(null);
  if (initialSearch.current === null) initialSearch.current = window.location.search;
  // Mount-only: a later toggle to key while sitting on Home leaves you there
  // (More highlights), so toggling mode never forces a navigation.
  useEffect(() => {
    if (
      appMode === "key" &&
      view === "home" &&
      !/[?&]view=/.test(initialSearch.current ?? "")
    ) {
      navigate({ view: "scan", set: null, card: null }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Selecting a tab clears both overlays, exactly as the previous state-based
  // version did. Stable identity (navigate is stable, and this reads nothing
  // from the current route), so the keydown effect below can hold it without
  // going stale.
  const selectTab = useCallback(
    (tab: TabView) => navigate({ view: tab, set: null, card: null }),
    [navigate],
  );

  // Overlays push a history entry, so Back peels one layer off the stack
  // (card → set → tab) instead of leaving the app. Opening a card keeps the
  // view and any open set beneath it, which is what makes sets → set → card
  // unwind one step at a time.
  function openCard(card: { cardId: string; variant?: string }) {
    navigate({ ...route, card });
  }
  // `back` walks the entry that opening the card pushed, so the in-app Back
  // button and the browser Back button agree. On a card that was deep-linked
  // or reloaded into there is no such entry, so it rewrites to the layer
  // underneath instead — the set detail if one is open, otherwise the tab.
  function closeCard() {
    back({ ...route, card: null });
  }
  function openSet(setId: string) {
    navigate({ ...route, set: setId, card: null });
  }
  function closeSet() {
    back({ ...route, set: null, card: null });
  }

  // Cmd/Ctrl+K toggles the command palette; Escape closes it. Digit-key
  // shortcuts (1-9) jump to tabs, but only when NOT typing in an input,
  // textarea, select, or contenteditable — so typing in a search box never
  // jumps tabs. Cmd/Ctrl+K and Escape always work.
  useEffect(() => {
    function isTyping() {
      const el = document.activeElement;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable;
    }
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (e.key === "Escape") {
        setPaletteOpen(false);
        return;
      }
      if (isTyping()) return;
      const map: Record<string, TabView> = {
        "1": "home", "2": "scan", "3": "vault", "4": "alerts",
        "5": "deals", "6": "prices", "7": "sealed", "8": "catalog", "9": "ledger",
      };
      if (map[e.key]) {
        e.preventDefault();
        selectTab(map[e.key]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectTab]);

  const title = selectedCard ? "Card" : selectedSet ? "Sets" : TAB_TITLES[view];

  // The nav is config-driven so the bottom-nav and the desktop sidebar render
  // from one source. Full mode shows every tab in the existing order; key mode
  // shows the curated seven (KEY_TAB_VIEWS) in the collector-loop order. The
  // glyph elements are rebuilt only when the mode changes.
  const navItems = useMemo<NavItem[]>(
    () => {
      const full: NavItem[] = [
        { view: "home", label: "Home", glyph: <HomeGlyph /> },
        { view: "scan", label: "Scan", glyph: <ScanGlyph /> },
        { view: "vault", label: "Vault", glyph: <VaultGlyph /> },
        { view: "binder", label: "Binder", glyph: <BinderGlyph /> },
        { view: "wants", label: "Wants", glyph: <WantsGlyph /> },
        { view: "alerts", label: "Alerts", glyph: <BellGlyph />, badge: "unread" },
        { view: "deals", label: "Deals", glyph: <TagGlyph /> },
        { view: "prices", label: "Prices", glyph: <PriceGlyph /> },
        { view: "sealed", label: "Sealed", glyph: <BoxGlyph /> },
        { view: "catalog", label: "Catalog", glyph: <CatalogGlyph /> },
        { view: "ledger", label: "Ledger", glyph: <LedgerGlyph /> },
        { view: "browse", label: "Browse", glyph: <SearchGlyph /> },
        { view: "sets", label: "Sets", glyph: <SetsGlyph /> },
        { view: "shop", label: "Shop", glyph: <ShopGlyph /> },
        { view: "more", label: "More", glyph: <MoreGlyph /> },
      ];
      if (appMode === "key") {
        return KEY_TAB_VIEWS.map(
          (v) => full.find((n) => n.view === v) as NavItem,
        );
      }
      return full;
    },
    [appMode],
  );

  // A tab is active when its view is showing and no card overlay is open. In
  // key mode, every non-key surface lives under More, so More stays highlighted
  // while one of them is open — the surface still renders, it is just not in the
  // curated nav. A card overlay over any view highlights nothing (Back is the
  // way out, not a tab).
  function isItemActive(item: NavItem): boolean {
    if (selectedCard) return false;
    if (view === item.view) return true;
    if (appMode === "key" && item.view === "more" && !KEY_TAB_VIEWS.includes(view)) {
      return true;
    }
    return false;
  }

  return (
    <main className="app app-shell">
      <header className="persistent-header app-header">
        <h1>{title}</h1>
        <button className="palette-trigger" onClick={() => setPaletteOpen(true)} aria-label="Search">
          <span aria-hidden="true">⌘K</span>
        </button>
      </header>

      <div className="app-content">
        <AnimatePresence mode="wait">
          {selectedCard ? (
            <PageTransition id="card">
              <CardDetail
                cardId={selectedCard.cardId}
                variant={selectedCard.variant}
                onBack={closeCard}
                onWatchCard={(c) => openWatchSheet(c)}
              />
            </PageTransition>
          ) : selectedSet ? (
            <PageTransition id="set">
              <SetDetail
                setId={selectedSet}
                onBack={closeSet}
                onSelectCard={(cardId) => openCard({ cardId })}
              />
            </PageTransition>
          ) : view === "home" ? (
            <PageTransition id="home">
              <Dashboard
                unread={unread}
                onNavigate={(tab) => selectTab(tab)}
                onWatchCard={() => openWatchSheet()}
              />
            </PageTransition>
          ) : view === "scan" ? (
            <PageTransition id="scan">
              <ScanPane
                scan={scan}
                onViewCard={(cardId) => openCard({ cardId })}
                onWatchCard={(card) => openWatchSheet(card)}
              />
            </PageTransition>
          ) : view === "vault" ? (
            <PageTransition id="vault">
              <PortfolioView />
            </PageTransition>
          ) : view === "binder" ? (
            <PageTransition id="binder">
              <Binder />
            </PageTransition>
          ) : view === "wants" ? (
            <PageTransition id="wants">
              <Wants />
            </PageTransition>
          ) : view === "alerts" ? (
            <PageTransition id="alerts">
              <AlertsFeed
                onOpenCard={(c) => openCard(c)}
                onWatchCard={(c) => openWatchSheet(c)}
              />
            </PageTransition>
          ) : view === "deals" ? (
            <PageTransition id="deals">
              <Deals onOpenCard={(c) => openCard(c)} />
            </PageTransition>
          ) : view === "prices" ? (
            <PageTransition id="prices">
              <PriceLookup />
            </PageTransition>
          ) : view === "ledger" ? (
            <PageTransition id="ledger">
              <SealedLedger />
            </PageTransition>
          ) : view === "sealed" ? (
            <PageTransition id="sealed">
              <SealedDeals />
            </PageTransition>
          ) : view === "catalog" ? (
            <PageTransition id="catalog">
              <SealedCatalog />
            </PageTransition>
          ) : view === "browse" ? (
            <PageTransition id="browse">
              <Browse onSelectCard={(c) => openCard(c)} />
            </PageTransition>
          ) : view === "sets" ? (
            <PageTransition id="sets">
              <Sets onSelectSet={(id) => openSet(id)} />
            </PageTransition>
          ) : view === "shop" ? (
            <PageTransition id="shop">
              <ShopAssistant />
            </PageTransition>
          ) : (
            <PageTransition id="more">
              <More appMode={appMode} onAppModeChange={onAppModeChange} />
            </PageTransition>
          )}
        </AnimatePresence>
      </div>

      {watchSheet.open && (
        <WatchCardSheet
          cardId={watchSheet.cardId}
          variant={watchSheet.variant}
          onClose={closeWatchSheet}
          onCreated={() => {
            refreshUnread();
            toast("Watch created", "success");
          }}
        />
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(tab) => selectTab(tab)}
        onSelectCard={(cardId) => {
          openCard({ cardId });
          setPaletteOpen(false);
        }}
      />

      {isDesktop ? (
        <DesktopNav
          items={navItems}
          isActive={isItemActive}
          unread={unread}
          onSelect={selectTab}
        />
      ) : (
        <nav className="bottom-nav" aria-label="Primary">
          {navItems.map((item) => (
            <TabButton
              key={item.view}
              label={item.label}
              active={isItemActive(item)}
              onClick={() => selectTab(item.view)}
              glyph={item.glyph}
              badge={item.badge === "unread" ? unread : undefined}
            />
          ))}
        </nav>
      )}
    </main>
  );
}

function DesktopNav({
  items,
  isActive,
  unread,
  onSelect,
}: {
  items: NavItem[];
  isActive: (item: NavItem) => boolean;
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
        {items.map((item) => (
          <TabButton
            key={item.view}
            label={item.label}
            active={isActive(item)}
            onClick={() => onSelect(item.view)}
            glyph={item.glyph}
            badge={item.badge === "unread" ? unread : undefined}
          />
        ))}
      </nav>
    </aside>
  );
}

function TabButton({
  label,
  active,
  onClick,
  glyph,
  badge,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  glyph: React.ReactNode;
  badge?: number;
}) {
  return (
    <button aria-current={active} onClick={onClick}>
      <span className="nav-glyph-wrap">
        {glyph}
        {badge !== undefined && badge > 0 && (
          <span className="nav-badge" aria-label={`${badge} unread alerts`}>
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </span>
      <span>{label}</span>
    </button>
  );
}

// The scan pane renders the existing CameraCapture → ScanResult flow exactly as
// App.tsx did, so no recognition behavior changes. The onboarding nudge is the
// Collectr-style "Watch this card" banner: after a successful scan resolving to a
// recognized card WITH a market price, surface a contextual prompt once per card
// (gated by a localStorage flag so it never nags). Tapping it opens WatchCardSheet
// preselected to that card. Non-blocking: a small banner, never a modal.
function ScanPane({
  scan,
  onViewCard,
  onWatchCard,
}: {
  scan: ScanFlow;
  onViewCard: (cardId: string) => void;
  onWatchCard: (card: { cardId: string; variant?: string }) => void;
}) {
  const {
    result,
    variant,
    scanId,
    busy,
    error,
    note,
    adjusting,
    lastImage,
    canAdjust,
    mode,
    onToggleMode,
    bulk,
  } = scan;

  // Onboarding nudge: only for a recognized card with a market price, and only
  // once per card. The flag is set when the banner is shown so a dismiss or a
  // tap both stop it reappearing — never nags. Suppressed in bulk mode.
  const card = result?.card ?? null;
  const hasMarketPrice = result?.price?.market != null;
  const nudgeKey = card ? `watch_nudge_${card.id}` : null;
  const [nudgeDismissed, setNudgeDismissed] = useState(false);
  const showNudge =
    mode === "single" &&
    !!card &&
    hasMarketPrice &&
    !!nudgeKey &&
    !localStorage.getItem(nudgeKey) &&
    !nudgeDismissed;

  function dismissNudge() {
    if (nudgeKey) localStorage.setItem(nudgeKey, "1");
    setNudgeDismissed(true);
  }

  // The single↔bulk toggle. Defaults to single so the existing flow renders
  // identically until the user opts in. The button's label is the mode it
  // switches TO, so it always reads as an action ("Bulk" / "Single").
  const toggleLabel = mode === "single" ? "Bulk" : "Single";

  return (
    <>
      <button
        className="header-toggle bulk-toggle"
        aria-pressed={mode === "bulk"}
        onClick={() => onToggleMode(mode === "single" ? "bulk" : "single")}
      >
        {toggleLabel} mode
      </button>

      {mode === "bulk" && bulk ? (
        <BulkPane bulk={bulk} />
      ) : (
        <>
          {!result && <CameraCapture onCapture={scan.onCapture} busy={busy} />}

          {error && <p className="error">{error}</p>}
          {note && <p className="note">{note}</p>}

          {result && adjusting && lastImage && (
            <CornerAdjust
              image={lastImage}
              onSubmit={scan.onCorners}
              onCancel={scan.onCancelAdjust}
            />
          )}

          {result && !adjusting && (
            <>
              <ScanResult
                result={result}
                variant={variant}
                scanId={scanId}
                onConfirm={scan.onConfirm}
                onPick={scan.onPick}
                onReject={scan.onReject}
                onRescan={scan.onRescan}
              />
              {card && (
                <button
                  className="link watch-scan-link"
                  onClick={() => onViewCard(card.id)}
                >
                  View card details
                </button>
              )}
              {showNudge && card && (
                <div className="watch-nudge" role="status">
                  <p className="muted small">
                    Want a ping when {card.name} restocks or hits your price?
                  </p>
                  <button
                    className="link"
                    onClick={() => {
                      dismissNudge();
                      onWatchCard({ cardId: card.id, variant });
                    }}
                  >
                    Watch this card
                  </button>
                  <button className="link nudge-dismiss" onClick={dismissNudge} aria-label="Dismiss">
                    Not now
                  </button>
                </div>
              )}
              {canAdjust && (
                <button className="adjust-offer" onClick={scan.onAdjust} disabled={busy}>
                  Place corners myself
                </button>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}

// The bulk review grid: one binder-page photo → N independent ScanResult cells.
// Each cell reuses ScanResult with its existing props; the per-index handlers
// (onConfirm/onPick/onReject/onRescan) are closures App wired in App.tsx. A
// per-cell variant selector lets the user override the variant before bulk-add;
// changing it re-renders that cell's ScanResult (and thus its PriceLine) with
// the new variant — a per-cell, user-initiated refetch, never a grid-render
// flood. Prices stay honest: a null price renders as "—" via formatMoney, never
// $0.00. The watch-nudge is suppressed in bulk (it is a single-card affordance).
function BulkPane({ bulk }: { bulk: BulkFlow }) {
  const {
    results,
    scanIds,
    variants,
    logStatus,
    busy,
    error,
    note,
    variantOptions,
    onCapture,
    onConfirm,
    onPick,
    onReject,
    onRescan,
    onVariantChange,
    onAddAll,
  } = bulk;

  const hasConfident = results.some((r) => r.status === "confident" && r.card);

  return (
    <>
      {results.length === 0 && <CameraCapture onCapture={onCapture} busy={busy} />}

      {error && <p className="error">{error}</p>}
      {note && <p className="note">{note}</p>}

      {results.length > 0 && (
        <>
          <div className="bulk-grid">
            {results.map((r, i) => (
              <div className="bulk-cell" key={i}>
                <ScanResult
                  result={r}
                  variant={variants[i] ?? "normal"}
                  scanId={scanIds[i] ?? null}
                  onConfirm={(p) => onConfirm(i, p)}
                  onPick={(c, p) => onPick(i, c, p)}
                  onReject={() => onReject(i)}
                  onRescan={() => onRescan(i)}
                />
                <label className="bulk-variant">
                  <span>Variant</span>
                  <select
                    value={variants[i] ?? "normal"}
                    onChange={(e) => onVariantChange(i, e.target.value)}
                  >
                    {variantOptions.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                {logStatus[i] && (
                  <span className={`bulk-log-status ${logStatus[i]}`}>
                    {logStatus[i] === "saved" ? "saved" : "save failed"}
                  </span>
                )}
              </div>
            ))}
          </div>
          {hasConfident && (
            <button className="primary bulk-add-all" onClick={onAddAll} disabled={busy}>
              Add all to collection
            </button>
          )}
        </>
      )}
    </>
  );
}

// Inline tab glyphs — same viewBox idiom as the prior two-tab nav, kept
// stroke-based so the active color flows from `currentColor`.
function HomeGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 11l8-6 8 6" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M6 10v9h12v-9" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M10 19v-5h4v5" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}
function ScanGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="6" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 6l1.5-2h5L16 6" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <circle cx="12" cy="13" r="3.2" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
function VaultGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <rect x="3.5" y="13.5" width="17" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
// A binder page — a card sleeve / sleeve-pocket, distinct from the Vault stack
// (the binder is a curated subset you show off, not the whole collection).
function BinderGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4" y="3" width="16" height="18" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <rect x="7" y="6.5" width="10" height="11" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="5.5" r="0.9" fill="currentColor" />
    </svg>
  );
}
// A hunting / target reticle — the Wants tab's glyph (the want list / hunt list:
// cards you're looking to acquire, with an optional target price). Distinct from
// the Binder sleeve (you don't own these yet) and from the Bell (alerts watch
// listing conditions; wants is a planning surface).
function WantsGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
function BellGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M10 19a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
function SearchGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="6" stroke="currentColor" strokeWidth="1.8" />
      <path d="M16 16l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
// A stacked set list with a partial progress bar — the Sets tab's glyph
// (per-set completion optimizer).
function SetsGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="4" width="18" height="4" rx="1" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="11" width="18" height="4" rx="1" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="18" width="11" height="3" rx="1" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}
function TagGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 12l7-7 8 8-7 7-8-8z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="9.5" cy="9.5" r="1.6" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
// A sealed booster box — the Sealed tab's glyph (query-keyed flip-edge deals).
function BoxGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 8l8-4 8 4-8 4-8-4z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M4 8v8l8 4 8-4V8"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M12 12v8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
// A ledger book — the Ledger tab's glyph (sealed-purchase purchase log).
function LedgerGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4" y="3" width="16" height="18" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 7h8M8 11h8M8 15h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
function MoreGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="5" cy="12" r="1.8" fill="currentColor" />
      <circle cx="12" cy="12" r="1.8" fill="currentColor" />
      <circle cx="19" cy="12" r="1.8" fill="currentColor" />
    </svg>
  );
}
// A price tag with a dollar sign — the Prices tab's glyph (card name -> price lookup).
function PriceGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3v18"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path
        d="M15 7.5C15 6 13.657 5.5 12 5.5c-1.657 0-3 .75-3 2.25S10.343 10 12 10s3 .75 3 2.25-1.343 2.25-3 2.25c-1.657 0-3-.5-3-2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
// A stacked catalog/grid — the Catalog tab's glyph (sealed-product reference catalog).
function CatalogGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
      <rect x="14" y="4" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
      <rect x="4" y="14" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
      <rect x="14" y="14" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
// A shopping bag with a checkmark — the Shop tab's glyph (paste-a-listing-URL
// assessment: deal / worth / authenticity read). Distinct from the Deals tag
// glyph (a price-tag) so the two deal surfaces stay visually separate.
function ShopGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 8h14l-1 12H6L5 8z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M9.5 14l1.8 1.8L15 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}