// Vault import (Row 30) — the symmetric pair to the Row 28 export. Bulk-add
// holdings from a CSV or JSON file (one exported by the app, or a spreadsheet
// you've kept elsewhere) into the vault, with honest skip-reporting for rows
// the catalog doesn't recognise and rows that are malformed.
//
// Honest: each valid row becomes a holding; rows whose card_id isn't in the
// catalog (or is missing, or has quantity < 1) are skipped with a reason —
// never silently dropped or coerced. Optional empty fields are null, never a
// fabricated $0. acquired_at is preserved on insert (the backend inserts rows
// directly rather than topping-up), so the Row 27 acquisition timeline stays
// accurate. The report lists every skipped row with its reason; an honest
// "0 added" with skips is shown, never a silent partial import.
//
// Local-first: the file is read in-browser by FileReader and POSTed as text;
// the report is rendered from the server's response. Nothing leaves the
// client+server pair.
import { useState } from "react";

import { importVault } from "../api/client";
import type { ImportReport } from "../api/types";

function detectFormat(name: string): "csv" | "json" {
  return name.toLowerCase().endsWith(".json") ? "json" : "csv";
}

export default function VaultImport() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);

  async function runImport(text: string, format: "csv" | "json") {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const result = await importVault(text, format);
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't import the file.");
    } finally {
      setBusy(false);
    }
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const format = detectFormat(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      void runImport(text, format);
    };
    reader.onerror = () => {
      setError("Couldn't read the file.");
      setReport(null);
    };
    reader.readAsText(file);
  }

  function handlePaste(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const text = String(data.get("text") ?? "");
    if (text.trim() === "") {
      setError("Paste a CSV or JSON body first.");
      setReport(null);
      return;
    }
    const format = String(data.get("format") ?? "csv") as "csv" | "json";
    void runImport(text, format);
    form.reset();
  }

  return (
    <section className="vault-import" aria-label="Vault import">
      <h3>Import into your vault</h3>
      <p className="muted small">
        Bulk-add holdings from a CSV or JSON file (e.g. one exported above). Rows are added directly so the imported
        purchase date is preserved; rows whose card isn't in the catalog, or are missing their card id, or have a
        quantity below 1, are skipped with a reason — never silently dropped. Optional empty fields are null, never $0.
      </p>

      <div className="vault-import-actions">
        <label className="btn btn-secondary">
          {busy ? "Importing…" : "Choose CSV/JSON file"}
          <input
            type="file"
            accept=".csv,.json,application/json,text/csv"
            onChange={handleFile}
            disabled={busy}
            hidden
          />
        </label>
      </div>

      <details className="vault-import-paste">
        <summary className="link">Or paste a body</summary>
        <form onSubmit={handlePaste}>
          <select name="format" aria-label="Format" defaultValue="csv">
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <textarea
            name="text"
            rows={6}
            aria-label="Paste body"
            placeholder="card_id,variant,quantity,condition,acquired_price,acquired_at,notes&#10;base1-4,normal,2,NM,20,2020-01-15,graded"
          />
          <button type="submit" className="btn btn-secondary" disabled={busy}>
            Import pasted body
          </button>
        </form>
      </details>

      {error && <p className="error small">{error}</p>}

      {report && (
        <div className="import-report">
          <h4>
            Imported {report.added} of {report.total} row{report.total === 1 ? "" : "s"}
            {report.skipped.length > 0 && (
              <span className="muted small"> · {report.skipped.length} skipped</span>
            )}
          </h4>
          {report.skipped.length > 0 ? (
            <table className="portfolio-table import-skip-table">
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Card id</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {report.skipped.map((s) => (
                  <tr key={s.row_number}>
                    <td data-label="Row">{s.row_number}</td>
                    <td data-label="Card id" className="muted">
                      {s.card_id ?? "—"}
                    </td>
                    <td data-label="Reason">{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            report.total > 0 && <p className="muted small">All rows added — no skips.</p>
          )}
          <p className="muted small">{report.caveat}</p>
        </div>
      )}
    </section>
  );
}