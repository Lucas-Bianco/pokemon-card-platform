import { useCallback, useEffect, useState } from "react";

import { addToCollection, confirmScan, correctScan, recognize, recordScan } from "./api/client";
import type { RecognizeResponse } from "./api/types";
import CameraCapture from "./components/CameraCapture";
import CornerAdjust from "./components/CornerAdjust";
import PortfolioView from "./components/PortfolioView";
import ScanResult from "./components/ScanResult";

const VARIANT = "normal";

export default function App() {
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Kept so a failed detection can be re-submitted with hand-placed corners rather
  // than making the user take the photo again.
  const [lastImage, setLastImage] = useState<Blob | null>(null);
  const [adjusting, setAdjusting] = useState(false);
  const [view, setView] = useState<"scan" | "portfolio">("scan");
  // Whether the app is running as an installed PWA (display-mode: standalone).
  // The bottom nav is only shown in that state; in-browser, the header toggle
  // is the sole navigation so the viewport stays uncluttered.
  const [standalone, setStandalone] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(display-mode: standalone)");
    setStandalone(mq.matches);
    const handler = (event: MediaQueryListEvent) => setStandalone(event.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Shared by the initial capture and the corner re-submission, so a corner-adjusted
  // scan is logged exactly like any other — the scan log is the project's only source
  // of real-photo ground truth and must not have a hole where the fallback was used.
  const runRecognition = useCallback(async (image: Blob, corners?: [number, number][]) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const response = await recognize(image, { rectify: true, variant: VARIANT, corners });
      setResult(response);
      // Log every scan, including failures — the not_found cases are the ones worth
      // studying, and this is the project's only source of real-photo ground truth.
      const scan = await recordScan(image, response).catch(() => null);
      setScanId(scan?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed.");
    } finally {
      setBusy(false);
      setAdjusting(false);
    }
  }, []);

  const handleCapture = useCallback(
    async (image: Blob) => {
      setLastImage(image);
      await runRecognition(image);
    },
    [runRecognition],
  );

  const handleCorners = useCallback(
    async (corners: [number, number][]) => {
      if (lastImage) await runRecognition(lastImage, corners);
    },
    [lastImage, runRecognition],
  );

  const handleConfirm = useCallback(
    async (acquiredPrice: number | null) => {
      if (result?.card) {
        await addToCollection(result.card.id, VARIANT, acquiredPrice).catch(() => null);
        setNote(`Added ${result.card.name} to your collection.`);
      }
      if (scanId !== null) await confirmScan(scanId).catch(() => null);
    },
    [result, scanId],
  );

  const handlePick = useCallback(
    async (cardId: string, acquiredPrice: number | null) => {
      await addToCollection(cardId, VARIANT, acquiredPrice).catch(() => null);
      if (scanId !== null) await correctScan(scanId, cardId).catch(() => null);
      setNote("Thanks — that correction helps the next scan.");
    },
    [scanId],
  );

  const handleReject = useCallback(() => {
    setNote("Marked as wrong. Scan it again, or try a darker background.");
  }, []);

  const handleRescan = useCallback(() => {
    setResult(null);
    setScanId(null);
    setNote(null);
    setError(null);
    setLastImage(null);
    setAdjusting(false);
  }, []);

  const canAdjust =
    lastImage !== null && (result?.status === "not_found" || result?.status === "ambiguous");

  return (
    <main className={`app${standalone ? " standalone" : ""}`}>
      {/* Persistent header — stays mounted across scan/portfolio so the title and
          the view toggle never re-mount or flicker when only the content swaps.
          padding-top carries the top safe-area inset (notch / status bar). */}
      <header className="persistent-header app-header">
        <h1>Card Scanner</h1>
        <div className="header-actions">
          <button
            className="header-toggle"
            aria-pressed={view === "portfolio"}
            onClick={() => setView(view === "scan" ? "portfolio" : "scan")}
          >
            {view === "scan" ? "Portfolio" : "Scan"}
          </button>
        </div>
      </header>

      {/* Content area — the only region that swaps between views. */}
      <div className="app-content">
        {view === "portfolio" ? (
          <PortfolioView />
        ) : (
          <>
            {!result && <CameraCapture onCapture={handleCapture} busy={busy} />}

            {error && <p className="error">{error}</p>}
            {note && <p className="note">{note}</p>}

            {result && adjusting && lastImage && (
              <CornerAdjust
                image={lastImage}
                onSubmit={handleCorners}
                onCancel={() => setAdjusting(false)}
              />
            )}

            {result && !adjusting && (
              <>
                <ScanResult
                  result={result}
                  variant={VARIANT}
                  onConfirm={handleConfirm}
                  onPick={handlePick}
                  onReject={handleReject}
                  onRescan={handleRescan}
                />
                {canAdjust && (
                  <button className="adjust-offer" onClick={() => setAdjusting(true)} disabled={busy}>
                    Place corners myself
                  </button>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* Bottom nav — PWA installed state only. Safe-area bottom inset is applied
          in styles.css so the bar clears the iOS home indicator. */}
      <nav className="bottom-nav" aria-label="Primary">
        <button aria-current={view === "scan"} onClick={() => setView("scan")}>
          <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3" y="6" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
            <path d="M8 6l1.5-2h5L16 6" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            <circle cx="12" cy="13" r="3.2" stroke="currentColor" strokeWidth="1.8" />
          </svg>
          <span>Scan</span>
        </button>
        <button aria-current={view === "portfolio"} onClick={() => setView("portfolio")}>
          <svg className="nav-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3.5" y="4.5" width="17" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
            <rect x="3.5" y="13.5" width="17" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
          </svg>
          <span>Portfolio</span>
        </button>
      </nav>
    </main>
  );
}