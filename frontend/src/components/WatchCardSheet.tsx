import { useEffect, useRef, useState } from "react";

import { createWatch, searchCards } from "../api/client";
import { ALERT_TYPES } from "../api/client";
import type { AlertType, CardSearchResult, Watch } from "../api/types";

interface Props {
  cardId?: string;
  variant?: string;
  onClose: () => void;
  onCreated?: (watch: Watch) => void;
}

// Per-type metadata: short label, description, whether a card is required, and
// whether a listings source is needed (the honest note). Kept in one place so
// the picker, conditional fields, and notes stay in lockstep. The "requires a
// listings source" note is HONEST: restock/new_listing/auction_ending all need
// eBay data the server only has when CARDPLATFORM_LISTINGS_API_KEY is set;
// drop_time is a pure scheduled reminder and needs no listings source.
const TYPE_INFO: Record<
  AlertType,
  { label: string; description: string; needsCard: boolean; needsListings: boolean }
> = {
  restock: {
    label: "Restock",
    description: "Ping me when this card is back in stock.",
    needsCard: true,
    needsListings: true,
  },
  new_listing: {
    label: "New listing",
    description: "Ping me when a new listing appears.",
    needsCard: true,
    needsListings: true,
  },
  price_target: {
    label: "Price target",
    description: "Ping me when the price drops to your target.",
    needsCard: true,
    needsListings: true,
  },
  auction_ending: {
    label: "Auction ending",
    description: "Ping me minutes before auctions end.",
    needsCard: true,
    needsListings: true,
  },
  drop_time: {
    label: "Drop time",
    description: "A scheduled reminder for a drop — no card needed.",
    needsCard: false,
    needsListings: false,
  },
  deal: {
    label: "Deal",
    description: "Ping me when a new listing clears the RIP/flip deal thresholds.",
    needsCard: true,
    needsListings: true,
  },
};

// A bottom-sheet modal for creating a watch. The alert-type picker shows the
// right conditional fields (target price / drop time + lead / auction window)
// and an honest note about what each type needs to fire. When no card is
// preselected, a small debounced card search lets the user pick one first;
// for drop_time a subject-label-only watch is allowed (e.g. a Pokémon Center
// vending drop with no card). 422s from the backend surface as a helpful error
// string rather than a bare status code.
export default function WatchCardSheet({ cardId, variant, onClose, onCreated }: Props) {
  const [alertType, setAlertType] = useState<AlertType>("restock");
  const [targetPrice, setTargetPrice] = useState("");
  const [dropAt, setDropAt] = useState("");
  const [leadTimeMin, setLeadTimeMin] = useState("");
  const [auctionWindowMin, setAuctionWindowMin] = useState("30");
  const [subjectLabel, setSubjectLabel] = useState("");

  // Card search state — only used when no cardId was passed in.
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CardSearchResult[]>([]);
  const [pickedCard, setPickedCard] = useState<CardSearchResult | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Watch | null>(null);

  // Debounced card search (reuses searchCards). The backend requires
  // min_length=1, so an empty query is never sent — mirroring Browse.
  useEffect(() => {
    if (cardId) return; // no search when a card is preselected
    const q = query.trim();
    if (q === "") {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearchBusy(true);
    const t = setTimeout(() => {
      searchCards(q)
        .then((rs) => {
          if (!cancelled) setResults(rs);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearchBusy(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, cardId]);

  // Keyboard-aware: focus the sheet so it scrolls when the soft keyboard opens.
  const sheetRef = useRef<HTMLDivElement>(null);

  const info = TYPE_INFO[alertType];
  const effectiveCardId = cardId ?? pickedCard?.id ?? null;

  // Client-side validation mirroring the backend's 422 rules. The backend is
  // the source of truth, but a helpful inline message is better than a network
  // round-trip for an obviously missing required field.
  function validate(): string | null {
    if (alertType === "price_target" && targetPrice.trim() === "") {
      return "Target price is required for a price-target watch.";
    }
    if (alertType === "price_target") {
      const n = Number(targetPrice);
      if (!Number.isFinite(n) || n <= 0) return "Enter a positive target price.";
    }
    if (alertType === "drop_time" && dropAt.trim() === "") {
      return "Drop time is required for a drop-time watch.";
    }
    if (alertType === "drop_time" && effectiveCardId === null && subjectLabel.trim() === "") {
      return "A drop-time watch without a card needs a subject label (e.g. 'Pokémon Center drop').";
    }
    if (info.needsCard && effectiveCardId === null) {
      return "Pick a card to watch — this alert type needs a card.";
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (created) return;
    const v = validate();
    if (v !== null) {
      setError(v);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const payload = {
        alert_type: alertType,
        card_id: effectiveCardId,
        subject_label: subjectLabel.trim() === "" ? null : subjectLabel.trim(),
        variant: variant ?? null,
        target_price: alertType === "price_target" ? Number(targetPrice) : null,
        drop_at: alertType === "drop_time" ? dropAt : null,
        lead_time_min:
          alertType === "drop_time" && leadTimeMin.trim() !== ""
            ? Number(leadTimeMin)
            : null,
        auction_window_min:
          alertType === "auction_ending" ? Number(auctionWindowMin) : null,
      };
      const watch = await createWatch(payload);
      setCreated(watch);
      onCreated?.(watch);
    } catch (err) {
      // expectJsonOrDetail surfaces the backend's 422 detail string here.
      setError(err instanceof Error ? err.message : "Couldn't create the watch.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="sheet-overlay" onClick={onClose}>
      <div
        className="sheet"
        ref={sheetRef}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Watch a card"
      >
        <div className="sheet-handle" aria-hidden="true" />
        <header className="sheet-head">
          <h3>{created ? "Watch added" : "Watch a card"}</h3>
          <button className="sheet-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {created ? (
          <div className="sheet-body">
            <p className="muted small">
              You'll be pinged the moment it fires. Manage this watch under More → Watchlist.
            </p>
            <button className="primary" onClick={onClose}>
              Done
            </button>
          </div>
        ) : (
          <form className="sheet-body" onSubmit={handleSubmit}>
            {/* Card selection: show the preselected card, or a search picker. */}
            {cardId ? (
              <div className="watch-card-fixed">
                <span className="muted small">Watching card</span>
                <strong>{cardId}</strong>
                {variant && <span className="muted small"> · {variant}</span>}
              </div>
            ) : (
              <div className="watch-card-search">
                <label className="watch-field">
                  <span>Card to watch{info.needsCard ? " (required)" : " (optional — leave blank for a drop reminder)"}</span>
                  <input
                    type="search"
                    placeholder="Search by card name"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                {searchBusy && <p className="muted small">Searching…</p>}
                {!searchBusy && query.trim() !== "" && results.length === 0 && (
                  <p className="muted small">No cards found.</p>
                )}
                {results.length > 0 && (
                  <ul className="sheet-search-results">
                    {results.slice(0, 8).map((r) => (
                      <li key={r.id}>
                        <button
                          type="button"
                          className={`sheet-search-row${pickedCard?.id === r.id ? " picked" : ""}`}
                          onClick={() => setPickedCard(r)}
                        >
                          <strong>{r.name}</strong>
                          <span className="muted small">
                            {r.set_name} · #{r.number}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {pickedCard && (
                  <p className="muted small">
                    Picked: {pickedCard.name} ({pickedCard.set_name} #{pickedCard.number})
                  </p>
                )}
                {/* subject_label is only meaningful for drop_time without a card. */}
                {alertType === "drop_time" && !pickedCard && (
                  <label className="watch-field">
                    <span>Subject label (e.g. 'Pokémon Center drop')</span>
                    <input
                      type="text"
                      placeholder="Pokémon Center vending drop"
                      value={subjectLabel}
                      onChange={(e) => setSubjectLabel(e.target.value)}
                    />
                  </label>
                )}
              </div>
            )}

            {/* Alert-type picker — 5 radio chips with short descriptions. */}
            <fieldset className="watch-type-picker">
              <legend className="muted small">Alert type</legend>
              <div className="watch-type-grid">
                {ALERT_TYPES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`watch-type-chip${alertType === t ? " selected" : ""}`}
                    aria-pressed={alertType === t}
                    onClick={() => setAlertType(t)}
                  >
                    <strong>{TYPE_INFO[t].label}</strong>
                    <span className="muted small">{TYPE_INFO[t].description}</span>
                  </button>
                ))}
              </div>
            </fieldset>

            {/* Conditional fields per type. */}
            {alertType === "price_target" && (
              <label className="watch-field">
                <span>Target price (required)</span>
                <input
                  name="target_price"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.01"
                  placeholder="—"
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(e.target.value)}
                />
              </label>
            )}

            {alertType === "drop_time" && (
              <>
                <label className="watch-field">
                  <span>Drop time (required)</span>
                  <input
                    name="drop_at"
                    type="datetime-local"
                    value={dropAt}
                    onChange={(e) => setDropAt(e.target.value)}
                  />
                </label>
                <label className="watch-field">
                  <span>Lead time (optional — minutes before the drop to be notified)</span>
                  <input
                    name="lead_time_min"
                    type="number"
                    min="0"
                    step="1"
                    placeholder="e.g. 10"
                    value={leadTimeMin}
                    onChange={(e) => setLeadTimeMin(e.target.value)}
                  />
                </label>
                <p className="muted small watch-note">
                  Works without a listings source — pure scheduled reminder.
                </p>
              </>
            )}

            {alertType === "auction_ending" && (
              <label className="watch-field">
                <span>Minutes before auctions end</span>
                <input
                  name="auction_window_min"
                  type="number"
                  min="0"
                  step="1"
                  value={auctionWindowMin}
                  onChange={(e) => setAuctionWindowMin(e.target.value)}
                />
              </label>
            )}

            {(alertType === "restock" || alertType === "new_listing") && (
              <p className="muted small watch-note">
                Requires a listings source key (eBay) to detect.
              </p>
            )}

            {error && <p className="error">{error}</p>}

            <button type="submit" className="primary" disabled={submitting}>
              {submitting ? "Watching…" : "Watch"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}