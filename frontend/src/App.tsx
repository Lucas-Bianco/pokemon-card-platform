import { useCallback, useState } from "react";

import { addToCollection, confirmScan, correctScan, recognize, recordScan } from "./api/client";
import type { RecognizeResponse } from "./api/types";
import CameraCapture from "./components/CameraCapture";
import CornerAdjust from "./components/CornerAdjust";
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
    <main className="app">
      <h1>Card Scanner</h1>

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
    </main>
  );
}
