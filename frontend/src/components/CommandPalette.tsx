// Cmd/Ctrl+K command palette: jump to any tab + search the catalog by name.
// Reuses searchCards (GET /cards?name=). The palette is an overlay rendered via
// AnimatePresence; when closed it renders nothing (so it adds no buttons to the
// DOM that could collide with test getByRole queries). Card results open the
// card detail view via onSelectCard. Honest-empty: a short query with no results
// shows "No matching cards.", never fabricated rows.
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { searchCards } from "../api/client";
import type { CardSearchResult } from "../api/types";

type Tab = "home" | "scan" | "vault" | "alerts" | "deals" | "ledger" | "sealed" | "browse" | "sets" | "more";

const TAB_COMMANDS: { tab: Tab; label: string; hint: string }[] = [
  { tab: "home", label: "Go to Home", hint: "Dashboard" },
  { tab: "scan", label: "Go to Scan", hint: "Scan a card" },
  { tab: "vault", label: "Go to Vault", hint: "Your collection" },
  { tab: "alerts", label: "Go to Alerts", hint: "Alert feed" },
  { tab: "deals", label: "Go to Deals", hint: "Deal sniper" },
  { tab: "sealed", label: "Go to Sealed", hint: "Sealed flip-edge" },
  { tab: "ledger", label: "Go to Ledger", hint: "Sealed purchases" },
  { tab: "browse", label: "Go to Browse", hint: "Catalog search" },
  { tab: "sets", label: "Go to Sets", hint: "Set completion" },
  { tab: "more", label: "Go to More", hint: "Settings" },
];

export function CommandPalette({
  open,
  onClose,
  onNavigate,
  onSelectCard,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (tab: Tab) => void;
  onSelectCard: (cardId: string) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CardSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset + focus on open.
  useEffect(() => {
    if (open) {
      setQ("");
      setResults([]);
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // Debounced card search (>=2 chars). Empty/short query is NOT sent.
  useEffect(() => {
    if (!open) return;
    const query = q.trim();
    if (query.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    let cancelled = false;
    const id = window.setTimeout(() => {
      searchCards(query)
        .then((r) => {
          if (!cancelled) setResults(r);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [q, open]);

  const showCards = q.trim().length >= 2;
  const commands = useMemo(
    () => (showCards ? [] : TAB_COMMANDS.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()))),
    [q, showCards],
  );

  function chooseTab(tab: Tab) {
    onNavigate(tab);
    onClose();
  }
  function chooseCard(cardId: string) {
    onSelectCard(cardId);
    onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="palette-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
          role="dialog"
          aria-label="Command palette"
        >
          <motion.div
            className="palette"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              className="palette-input"
              placeholder="Search cards or jump to a tab…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") onClose();
              }}
              aria-label="Command palette search"
            />
            <div className="palette-results">
              {showCards ? (
                searching ? (
                  <p className="muted small palette-hint">Searching…</p>
                ) : results.length === 0 ? (
                  <p className="muted small palette-hint">No matching cards.</p>
                ) : (
                  <ul className="palette-cards">
                    {results.slice(0, 8).map((c) => (
                      <li key={c.id}>
                        <button className="palette-card" onClick={() => chooseCard(c.id)}>
                          <span className="palette-card-name">{c.name}</span>
                          <span className="palette-card-set">{c.set_name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )
              ) : (
                <ul className="palette-commands">
                  {commands.map((c) => (
                    <li key={c.tab}>
                      <button className="palette-command" onClick={() => chooseTab(c.tab)}>
                        <span>{c.label}</span>
                        <span className="muted small">{c.hint}</span>
                      </button>
                    </li>
                  ))}
                  {commands.length === 0 && <p className="muted small palette-hint">No matching commands.</p>}
                </ul>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}