import { useEffect, useState } from "react";

import { getUnreadCount } from "../api/client";
import type { RecognizeResponse } from "../api/types";
import AlertsFeed from "./AlertsFeed";
import CameraCapture from "./CameraCapture";
import CardDetail from "./CardDetail";
import CornerAdjust from "./CornerAdjust";
import Browse from "./Browse";
import Deals from "./Deals";
import More from "./More";
import PortfolioView from "./PortfolioView";
import ScanResult from "./ScanResult";
import SealedDeals from "./SealedDeals";
import WatchCardSheet from "./WatchCardSheet";

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

type TabView = "scan" | "vault" | "alerts" | "deals" | "sealed" | "browse" | "more";

interface Props {
  scan: ScanFlow;
}

const TAB_TITLES: Record<TabView, string> = {
  scan: "Scan",
  vault: "Vault",
  alerts: "Alerts",
  deals: "Deals",
  sealed: "Sealed",
  browse: "Browse",
  more: "More",
};

// Five-tab shell: Alerts-first (the alert feed is the landing surface — T7 ships
// the live feed; T6 lands the tab + an honest empty-state placeholder). The
// bottom nav is always visible now that there are 5 surfaces — the prior
// in-browser header toggle did not scale beyond two tabs. A slim header carries
// the active title. CardDetail renders as a transient detail view over the
// current tab; back returns to it.
export default function AppShell({ scan }: Props) {
  const [view, setView] = useState<TabView>("alerts");
  const [selectedCard, setSelectedCard] = useState<{ cardId: string; variant?: string } | null>(null);
  const [unread, setUnread] = useState(0);
  // The WatchCardSheet is app-level so any surface (AlertsFeed empty-state
  // CTA, CardDetail "Watch this card", the scan onboarding nudge) can open it
  // preselected to a card. `card` is undefined for the no-preselect CTA.
  const [watchSheet, setWatchSheet] = useState<{
    open: boolean;
    cardId?: string;
    variant?: string;
  }>({ open: false });

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

  function selectTab(tab: TabView) {
    setSelectedCard(null);
    setView(tab);
  }

  const title = selectedCard ? "Card" : TAB_TITLES[view];

  return (
    <main className="app app-shell">
      <header className="persistent-header app-header">
        <h1>{title}</h1>
      </header>

      <div className="app-content">
        {selectedCard ? (
          <CardDetail
            cardId={selectedCard.cardId}
            variant={selectedCard.variant}
            onBack={() => setSelectedCard(null)}
            onWatchCard={(c) => openWatchSheet(c)}
          />
        ) : view === "scan" ? (
          <ScanPane
            scan={scan}
            onViewCard={(cardId) => setSelectedCard({ cardId })}
            onWatchCard={(card) => openWatchSheet(card)}
          />
        ) : view === "vault" ? (
          <PortfolioView />
        ) : view === "alerts" ? (
          <AlertsFeed
            onOpenCard={(c) => setSelectedCard(c)}
            onWatchCard={(c) => openWatchSheet(c)}
          />
        ) : view === "deals" ? (
          <Deals onOpenCard={(c) => setSelectedCard(c)} />
        ) : view === "sealed" ? (
          <SealedDeals />
        ) : view === "browse" ? (
          <Browse onSelectCard={(c) => setSelectedCard(c)} />
        ) : (
          <More />
        )}
      </div>

      {watchSheet.open && (
        <WatchCardSheet
          cardId={watchSheet.cardId}
          variant={watchSheet.variant}
          onClose={closeWatchSheet}
          onCreated={() => refreshUnread()}
        />
      )}

      <nav className="bottom-nav" aria-label="Primary">
        <TabButton label="Scan" active={view === "scan" && !selectedCard} onClick={() => selectTab("scan")} glyph={<ScanGlyph />} />
        <TabButton label="Vault" active={view === "vault" && !selectedCard} onClick={() => selectTab("vault")} glyph={<VaultGlyph />} />
        <TabButton
          label="Alerts"
          active={view === "alerts" && !selectedCard}
          onClick={() => selectTab("alerts")}
          glyph={<BellGlyph />}
          badge={unread}
        />
        <TabButton
          label="Deals"
          active={view === "deals" && !selectedCard}
          onClick={() => selectTab("deals")}
          glyph={<TagGlyph />}
        />
        <TabButton
          label="Sealed"
          active={view === "sealed" && !selectedCard}
          onClick={() => selectTab("sealed")}
          glyph={<BoxGlyph />}
        />
        <TabButton label="Browse" active={view === "browse" && !selectedCard} onClick={() => selectTab("browse")} glyph={<SearchGlyph />} />
        <TabButton label="More" active={view === "more" && !selectedCard} onClick={() => selectTab("more")} glyph={<MoreGlyph />} />
      </nav>
    </main>
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
function MoreGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="5" cy="12" r="1.8" fill="currentColor" />
      <circle cx="12" cy="12" r="1.8" fill="currentColor" />
      <circle cx="19" cy="12" r="1.8" fill="currentColor" />
    </svg>
  );
}