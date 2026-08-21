import { useCallback, useState } from "react";

import {
  addToCollection,
  batchRecognize,
  confirmScan,
  correctScan,
  recognize,
  recordScan,
} from "./api/client";
import type { RecognizeResponse } from "./api/types";
import AppShell from "./components/AppShell";
import { useToast } from "./components/Toast";

const VARIANT = "normal";

// The variant picker offered per bulk cell. The single-card path hardcodes
// VARIANT="normal"; bulk repeats the same option set so a per-cell override is
// always one of the strings the price/grading endpoints accept. Kept small —
// these are the three TCGplayer variants the backend resolves.
const BULK_VARIANTS = ["normal", "holofoil", "reverseHolofoil"];

// A 3x3 binder page is the default; the backend clamps to [1, 18].
const BULK_MAX_CARDS = 9;

// App owns the recognition state + scan-log callbacks (the project's only
// source of real-photo ground truth); the 5-tab chrome lives in AppShell. The
// prior 2-view toggle + standalone bottom-nav gating is gone — 5 surfaces need
// a persistent bottom nav in-browser and PWA alike.
export default function App() {
  const { toast } = useToast();
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Kept so a failed detection can be re-submitted with hand-placed corners rather
  // than making the user take the photo again.
  const [lastImage, setLastImage] = useState<Blob | null>(null);
  const [adjusting, setAdjusting] = useState(false);

  // --- Bulk mode (Phase 4) --------------------------------------------------
  // Additive: the single-card state above is untouched. `mode` defaults to
  // "single" so the existing render + handlers behave identically until the
  // user opts into bulk. Per-cell state is kept parallel by index — results,
  // logged scan ids, per-cell overridden variants, and a small saved/failed
  // logging indicator. Prices are never fabricated: a null price flows through
  // to ScanResult → PriceLine → formatMoney → "—".
  const [mode, setMode] = useState<"single" | "bulk">("single");
  const [bulkResults, setBulkResults] = useState<RecognizeResponse[]>([]);
  const [bulkBatchId, setBulkBatchId] = useState<string | null>(null);
  const [bulkScanIds, setBulkScanIds] = useState<(number | null)[]>([]);
  const [bulkVariants, setBulkVariants] = useState<string[]>([]);
  const [bulkLogStatus, setBulkLogStatus] = useState<("saved" | "failed" | null)[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkNote, setBulkNote] = useState<string | null>(null);

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
        toast("Added to collection", "success");
      }
      if (scanId !== null) await confirmScan(scanId).catch(() => null);
    },
    [result, scanId, toast],
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

  // Switching modes clears the other mode's state so a stale single-card result
  // never coexists with a stale bulk grid. The single-card state reset mirrors
  // handleRescan so the toggle is a clean slate in both directions.
  const switchMode = useCallback(
    (next: "single" | "bulk") => {
      if (next === "bulk") {
        setResult(null);
        setScanId(null);
        setNote(null);
        setError(null);
        setLastImage(null);
        setAdjusting(false);
      } else {
        setBulkResults([]);
        setBulkBatchId(null);
        setBulkScanIds([]);
        setBulkVariants([]);
        setBulkLogStatus([]);
        setBulkError(null);
        setBulkNote(null);
      }
      setMode(next);
    },
    [],
  );

  // Bulk recognition: one binder-page photo → N independent verdicts. Each card
  // is logged via recordScan with batch_id + batch_index + the rectified crop
  // threaded through, so the scan log keeps its per-card granularity. Logging
  // failures are surfaced per cell (saved/failed) rather than swallowed — the
  // scan log is the project's only real-photo ground truth.
  const runBulkRecognition = useCallback(async (image: Blob) => {
    setBulkBusy(true);
    setBulkError(null);
    setBulkNote(null);
    setBulkResults([]);
    setBulkScanIds([]);
    setBulkVariants([]);
    setBulkLogStatus([]);
    setBulkBatchId(null);
    try {
      const response = await batchRecognize(image, VARIANT, BULK_MAX_CARDS);
      const n = response.results.length;
      setBulkResults(response.results);
      setBulkBatchId(response.batch_id);
      setBulkScanIds(new Array(n).fill(null));
      setBulkVariants(new Array(n).fill(VARIANT));
      setBulkLogStatus(new Array(n).fill(null));
      // Log each card in parallel; settle each cell's status independently so
      // one slow/failed POST never blocks the others or the grid render.
      response.results.forEach((res, i) => {
        recordScan(image, res, {
          batch_id: response.batch_id,
          batch_index: i,
          rectified_path: res.rectified_path ?? null,
          variant: VARIANT,
        })
          .then((scan) => {
            setBulkScanIds((prev) => {
              const next = [...prev];
              next[i] = scan.id;
              return next;
            });
            setBulkLogStatus((prev) => {
              const next = [...prev];
              next[i] = "saved";
              return next;
            });
          })
          .catch(() => {
            setBulkLogStatus((prev) => {
              const next = [...prev];
              next[i] = "failed";
              return next;
            });
          });
      });
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : "Bulk scan failed.");
    } finally {
      setBulkBusy(false);
    }
  }, []);

  const handleBulkCapture = useCallback(
    async (image: Blob) => {
      await runBulkRecognition(image);
    },
    [runBulkRecognition],
  );

  const handleBulkConfirm = useCallback(
    async (i: number, acquiredPrice: number | null) => {
      const res = bulkResults[i];
      const variant = bulkVariants[i] ?? VARIANT;
      if (res?.card) {
        await addToCollection(res.card.id, variant, acquiredPrice).catch(() => null);
        setBulkNote(`Added ${res.card.name} to your collection.`);
      }
      const scanId = bulkScanIds[i];
      if (scanId !== null && scanId !== undefined) {
        await confirmScan(scanId).catch(() => null);
      }
    },
    [bulkResults, bulkVariants, bulkScanIds],
  );

  const handleBulkPick = useCallback(
    async (i: number, cardId: string, acquiredPrice: number | null) => {
      const variant = bulkVariants[i] ?? VARIANT;
      await addToCollection(cardId, variant, acquiredPrice).catch(() => null);
      const scanId = bulkScanIds[i];
      if (scanId !== null && scanId !== undefined) {
        await correctScan(scanId, cardId).catch(() => null);
      }
      setBulkNote("Thanks — that correction helps the next scan.");
    },
    [bulkVariants, bulkScanIds],
  );

  const handleBulkReject = useCallback((i: number) => {
    setBulkNote(`Cell ${i + 1} marked wrong. Scan it again, or try a darker background.`);
  }, []);

  // Per-cell rescan is not feasible without per-cell crops, so a per-cell
  // "Scan another" resets the whole batch — the user re-shoots the page. This
  // matches the cell's "Scan another" affordance honestly rather than no-op'ing.
  const handleBulkRescan = useCallback(() => {
    setBulkResults([]);
    setBulkBatchId(null);
    setBulkScanIds([]);
    setBulkVariants([]);
    setBulkLogStatus([]);
    setBulkError(null);
    setBulkNote(null);
  }, []);

  const handleBulkVariantChange = useCallback((i: number, variant: string) => {
    setBulkVariants((prev) => {
      const next = [...prev];
      next[i] = variant;
      return next;
    });
  }, []);

  // Bulk-add: one call per distinct (card_id, variant) among confident results.
  // The store merges duplicates on its side. No acquired price is fabricated —
  // the per-cell "add to collection" affordance collects one when known; bulk-add
  // is the quick path for a fresh binder page and leaves the cost basis null.
  const handleBulkAddAll = useCallback(async () => {
    const seen = new Set<string>();
    for (let i = 0; i < bulkResults.length; i++) {
      const res = bulkResults[i];
      if (res.status !== "confident" || !res.card) continue;
      const variant = bulkVariants[i] ?? VARIANT;
      const key = `${res.card.id}|${variant}`;
      if (seen.has(key)) continue;
      seen.add(key);
      await addToCollection(res.card.id, variant, null).catch(() => null);
    }
    const added = seen.size;
    setBulkNote(added > 0 ? `Added ${added} card${added === 1 ? "" : "s"} to your collection.` : "No confident cards to add.");
    if (added > 0) toast(`Added ${added} card${added === 1 ? "" : "s"} to your collection.`, "success");
  }, [bulkResults, bulkVariants, toast]);

  const canAdjust =
    lastImage !== null && (result?.status === "not_found" || result?.status === "ambiguous");

  return (
    <AppShell
      scan={{
        result,
        variant: VARIANT,
        scanId,
        busy,
        error,
        note,
        adjusting,
        lastImage,
        canAdjust,
        onCapture: handleCapture,
        onCorners: handleCorners,
        onConfirm: handleConfirm,
        onPick: handlePick,
        onReject: handleReject,
        onRescan: handleRescan,
        onAdjust: () => setAdjusting(true),
        onCancelAdjust: () => setAdjusting(false),
        // Bulk mode (additive). `bulk` is null in single mode so AppShell's
        // ScanPane never touches it on the single-card path.
        mode,
        onToggleMode: switchMode,
        bulk: mode === "bulk"
          ? {
              results: bulkResults,
              batchId: bulkBatchId,
              scanIds: bulkScanIds,
              variants: bulkVariants,
              logStatus: bulkLogStatus,
              busy: bulkBusy,
              error: bulkError,
              note: bulkNote,
              variantOptions: BULK_VARIANTS,
              onCapture: handleBulkCapture,
              onConfirm: handleBulkConfirm,
              onPick: handleBulkPick,
              onReject: handleBulkReject,
              onRescan: handleBulkRescan,
              onVariantChange: handleBulkVariantChange,
              onAddAll: handleBulkAddAll,
            }
          : null,
      }}
    />
  );
}