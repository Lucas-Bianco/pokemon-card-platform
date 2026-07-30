import { useCallback, useState } from "react";

import { addToCollection, confirmScan, correctScan, recognize, recordScan } from "./api/client";
import type { RecognizeResponse } from "./api/types";
import CameraCapture from "./components/CameraCapture";
import ScanResult from "./components/ScanResult";

const VARIANT = "normal";

export default function App() {
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const handleCapture = useCallback(async (image: Blob) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const response = await recognize(image, { rectify: true, variant: VARIANT });
      setResult(response);
      // Log every scan, including failures — the not_found cases are the ones worth
      // studying, and this is the project's only source of real-photo ground truth.
      const scan = await recordScan(image, response).catch(() => null);
      setScanId(scan?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  const handleConfirm = useCallback(async () => {
    if (result?.card) {
      await addToCollection(result.card.id, VARIANT).catch(() => null);
      setNote(`Added ${result.card.name} to your collection.`);
    }
    if (scanId !== null) await confirmScan(scanId).catch(() => null);
  }, [result, scanId]);

  const handlePick = useCallback(
    async (cardId: string) => {
      await addToCollection(cardId, VARIANT).catch(() => null);
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
  }, []);

  return (
    <main className="app">
      <h1>Card Scanner</h1>

      {!result && <CameraCapture onCapture={handleCapture} busy={busy} />}

      {error && <p className="error">{error}</p>}
      {note && <p className="note">{note}</p>}

      {result && (
        <ScanResult
          result={result}
          variant={VARIANT}
          onConfirm={handleConfirm}
          onPick={handlePick}
          onReject={handleReject}
          onRescan={handleRescan}
        />
      )}
    </main>
  );
}
