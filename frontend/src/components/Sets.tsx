import { useEffect, useRef, useState } from "react";

import { getSets } from "../api/client";
import type { SetProgress } from "../api/types";

interface Props {
  onSelectSet: (setId: string) => void;
}

type State =
  | { kind: "idle" }
  | { kind: "searching"; query: string }
  | { kind: "results"; query: string; sets: SetProgress[] }
  | { kind: "error"; message: string };

// The 10th tab: searchable list of every set in the catalog with per-set
// completion progress. All valuation is server-side (getSets returns owned/total
// only — no price fan-out here); the client never resolves prices itself.
export default function Sets({ onSelectSet }: Props) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const reqId = useRef(0);

  useEffect(() => {
    const id = ++reqId.current;
    const trimmed = query.trim();
    // On mount (empty query) we load the newest sets immediately so the tab is
    // never blank; a typed query debounces and refines.
    const delay = trimmed === "" ? 0 : 250;
    if (delay > 0) setState({ kind: "searching", query: trimmed });
    let cancelled = false;
    const t = setTimeout(() => {
      getSets(trimmed || undefined)
        .then((sets) => {
          if (cancelled || id !== reqId.current) return;
          setState({ kind: "results", query: trimmed, sets });
        })
        .catch(() => {
          if (cancelled || id !== reqId.current) return;
          setState({ kind: "error", message: "Could not load sets." });
        });
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query]);

  return (
    <section className="sets">
      <h2>Sets</h2>
      <p className="muted small">Track completion for every set in the catalog.</p>
      <input
        className="sets-input"
        type="search"
        placeholder="Search sets by name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search sets"
      />

      {state.kind === "searching" && <p className="muted">Searching…</p>}
      {state.kind === "error" && <p className="error">{state.message}</p>}
      {state.kind === "results" && state.sets.length === 0 && (
        <p className="sets-empty muted">No sets found for “{state.query}”.</p>
      )}
      {state.kind === "results" && state.sets.length > 0 && (
        <ul className="sets-list">
          {state.sets.map((s) => {
            const pct = Math.round(s.pct_complete * 100);
            return (
              <li key={s.id}>
                <button className="sets-row" onClick={() => onSelectSet(s.id)}>
                  <span className="sets-row-name">{s.name}</span>
                  <span className="sets-row-meta muted small">
                    {s.series ? `${s.series} · ` : ""}
                    {s.release_date ? s.release_date.slice(0, 4) : ""}
                  </span>
                  <span className="sets-progress" aria-hidden="true">
                    <span
                      className="sets-progress-fill"
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                  <span className="sets-row-count">
                    {s.owned} / {s.checklist_size} owned · {pct}%
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {state.kind === "idle" && (
        <p className="browse-hint muted">Search 170+ sets by name to see completion.</p>
      )}
    </section>
  );
}