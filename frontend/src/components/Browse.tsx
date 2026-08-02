import { useEffect, useRef, useState } from "react";

import { searchCards } from "../api/client";
import type { CardSearchResult } from "../api/types";

interface Props {
  onSelectCard: (selection: { cardId: string; variant?: string }) => void;
}

type State =
  | { kind: "idle" }
  | { kind: "searching"; query: string }
  | { kind: "results"; query: string; results: CardSearchResult[] }
  | { kind: "empty"; query: string }
  | { kind: "error"; message: string };

// Catalog search. The backend's GET /cards requires min_length=1, so an empty
// query is never sent — the user sees a hint instead. Debounced 300ms so each
// keystroke does not hammer the catalog. Honest empty: no matches → "No cards
// found for '<query>'." Never fabricate a card.
export default function Browse({ onSelectCard }: Props) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  // A monotonically increasing token so a late-arriving response for an older
  // query cannot overwrite the results for the current one (the stale-response
  // race that debounce alone does not solve).
  const reqToken = useRef(0);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed === "") {
      setState({ kind: "idle" });
      return;
    }
    const token = ++reqToken.current;
    setState({ kind: "searching", query: trimmed });
    const handle = window.setTimeout(() => {
      let cancelled = false;
      async function run() {
        try {
          const results = await searchCards(trimmed);
          // A newer keystroke superseded this one — drop the stale result.
          if (token !== reqToken.current || cancelled) return;
          if (results.length === 0) {
            setState({ kind: "empty", query: trimmed });
          } else {
            setState({ kind: "results", query: trimmed, results });
          }
        } catch (err) {
          if (token !== reqToken.current || cancelled) return;
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Search failed.",
          });
        }
      }
      void run();
      return () => {
        cancelled = true;
      };
    }, 300);
    return () => {
      window.clearTimeout(handle);
    };
  }, [query]);

  return (
    <section className="browse">
      <input
        type="search"
        className="browse-input"
        placeholder="Search by card name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search cards by name"
        autoComplete="off"
      />

      {state.kind === "idle" && (
        <p className="browse-hint muted">Search 20,000+ cards by name.</p>
      )}

      {state.kind === "searching" && <p className="muted">Searching…</p>}

      {state.kind === "error" && <p className="error">{state.message}</p>}

      {state.kind === "empty" && (
        <p className="browse-empty muted">No cards found for “{state.query}”.</p>
      )}

      {state.kind === "results" && (
        <ul className="browse-results">
          {state.results.map((r) => (
            <li key={r.id}>
              <button
                className="browse-result"
                onClick={() => onSelectCard({ cardId: r.id, variant: undefined })}
              >
                {r.image_small ? (
                  <img src={r.image_small} alt="" className="browse-thumb" />
                ) : (
                  <span className="browse-thumb placeholder" aria-hidden="true" />
                )}
                <span className="browse-result-text">
                  <strong>{r.name}</strong>
                  <span className="muted small">
                    {r.set_name} · #{r.number}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}