import { useEffect, useState } from "react";

import { getUnreadCount } from "../api/client";
import type { RecognizeResponse } from "../api/types";
import CameraCapture from "./CameraCapture";
import CardDetail from "./CardDetail";
import CornerAdjust from "./CornerAdjust";
import Browse from "./Browse";
import PortfolioView from "./PortfolioView";
import ScanResult from "./ScanResult";

// The scan flow stays owned by App (which holds the recognition state and the
// scan-log callbacks); AppShell receives it as a bundle so it can render the
// Scan tab without knowing the recognition mechanics.
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
}

type TabView = "scan" | "vault" | "alerts" | "browse" | "more";

interface Props {
  scan: ScanFlow;
}

const TAB_TITLES: Record<TabView, string> = {
  scan: "Scan",
  vault: "Vault",
  alerts: "Alerts",
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

  // Unread badge for the Alerts tab. Fetched on mount for T6; T7 adds the live
  // feed + polling. A failed count is honest zero (no fake badge), not an error.
  useEffect(() => {
    let cancelled = false;
    getUnreadCount()
      .then((count) => {
        if (!cancelled) setUnread(count);
      })
      .catch(() => {
        if (!cancelled) setUnread(0);
      });
    return () => {
      cancelled = true;
    };
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
          />
        ) : view === "scan" ? (
          <ScanPane scan={scan} onWatchCard={(cardId) => setSelectedCard({ cardId })} />
        ) : view === "vault" ? (
          <PortfolioView />
        ) : view === "alerts" ? (
          <AlertsPlaceholder onWatchCard={() => setView("browse")} />
        ) : view === "browse" ? (
          <Browse onSelectCard={(c) => setSelectedCard(c)} />
        ) : (
          <MorePane />
        )}
      </div>

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
// App.tsx did, so no recognition behavior changes. On a recognized scan it
// surfaces a "Watch this card" affordance that opens CardDetail — T7 wires the
// real onboarding sheet; here it only makes the card reachable.
function ScanPane({ scan, onWatchCard }: { scan: ScanFlow; onWatchCard: (cardId: string) => void }) {
  const { result, variant, scanId, busy, error, note, adjusting, lastImage, canAdjust } = scan;
  return (
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
          {result.card && (
            <button
              className="link watch-scan-link"
              onClick={() => onWatchCard(result.card!.id)}
            >
              View card details
            </button>
          )}
          {canAdjust && (
            <button className="adjust-offer" onClick={scan.onAdjust} disabled={busy}>
              Place corners myself
            </button>
          )}
        </>
      )}
    </>
  );
}

// T7 replaces this with the live alert feed. The placeholder is an honest empty
// state — never a fabricated alert. The "Watch a card" button routes to Browse
// (where a card can be selected → CardDetail → real watch setup lands in T7).
function AlertsPlaceholder({ onWatchCard }: { onWatchCard: () => void }) {
  return (
    <section className="alerts-placeholder">
      <p className="alerts-radar">
        Your personal card-market radar — watch a card to get pinged the moment it restocks, hits your
        price, or a drop happens.
      </p>
      <button className="primary" disabled title="Watchlist setup coming soon">
        Watch a card
      </button>
      <button className="link" onClick={onWatchCard}>
        Browse cards
      </button>
    </section>
  );
}

function MorePane() {
  return (
    <section className="more-pane">
      <p className="muted">More coming soon.</p>
    </section>
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
function MoreGlyph() {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="5" cy="12" r="1.8" fill="currentColor" />
      <circle cx="12" cy="12" r="1.8" fill="currentColor" />
      <circle cx="19" cy="12" r="1.8" fill="currentColor" />
    </svg>
  );
}