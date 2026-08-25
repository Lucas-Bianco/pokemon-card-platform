// Vault export (Row 28) — download the full holding schedule as a CSV or JSON
// file. The serious-collector utility: get your vault out as a spreadsheet so
// you can reconcile it, back it up, or import it elsewhere. Local-first, like
// the binder HTML export — the browser builds the file from the server's body
// and downloads it; nothing is uploaded anywhere.
//
// Honest: reuses the same portfolio serialization the Vault renders, so the
// export and the app can never disagree on a price. An unpriced holding exports
// with a blank market-price cell / null field and no source — never $0. The
// note says so verbatim so the blank cell is never mistaken for a zero value.
import { useState } from "react";

import { exportVault } from "../api/client";

const MIME: Record<"csv" | "json", string> = {
  csv: "text/csv",
  json: "application/json",
};

const FILENAME: Record<"csv" | "json", string> = {
  csv: "vault-export.csv",
  json: "vault-export.json",
};

export default function VaultExport() {
  const [busy, setBusy] = useState<"csv" | "json" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleExport(format: "csv" | "json") {
    setBusy(format);
    setError(null);
    try {
      const text = await exportVault(format);
      const blob = new Blob([text], { type: `${MIME[format]};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = FILENAME[format];
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't export the vault.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="vault-export" aria-label="Vault export">
      <h3>Export your vault</h3>
      <p className="muted small">
        Download every holding — card, set, variant, quantity, paid, market price + source, and unrealized P/L — as a
        spreadsheet or JSON file. Unpriced cards export with a blank market price, never $0.
      </p>
      <div className="vault-export-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => handleExport("csv")}
          disabled={busy !== null}
        >
          {busy === "csv" ? "Exporting…" : "Export CSV"}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => handleExport("json")}
          disabled={busy !== null}
        >
          {busy === "json" ? "Exporting…" : "Export JSON"}
        </button>
      </div>
      {error && <p className="error small">{error}</p>}
    </section>
  );
}