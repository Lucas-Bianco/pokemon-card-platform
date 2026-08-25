import { useEffect, useState } from "react";

import {
  getWants,
  patchWantItem,
  removeWantItem,
} from "../api/client";
import type { WantItem } from "../api/types";
import { formatMoney } from "../lib/format";

// The Wants tab (roadmap row 24): a planning surface — cards you want to
// *acquire*. Distinct from the binder (cards you own and show off) and from
// alerts (which watch listing conditions). One slot per (card_id, variant),
// carrying an optional `target_price` (what you'd be willing to pay — null is
// honest "no target") and a free-form note. Each slot is joined at read time to
// its catalog row + `PriceService.latest_price` (the same reference the rest of
// the app uses).
//
// HONESTY (the whole feature):
// - `market_price` is the resolved market figure or null: a slot with no
//   market price shows "No market price yet" (an em dash in the price column),
//   NEVER a fabricated $0.
// - `deal_gap` (`target_price - market_price`) and `within_target` are null
//   when EITHER side is missing — never a guess. A slot with a target but no
//   market price shows the target and an honest "no market price to compare".
// - Target price is optional; "no target" is honest, never coerced to $0.
//
// Do-not-break: no button here is named "Scan", and no CTA collides with a nav
// tab label — "Set target" / "Save target" / "Clear target" / "Add note" /
// "Save note" / "Remove from wants" are all distinct verb-phrases.

type LoadState = "loading" | "ready" | "error";

export default function Wants() {
  const [items, setItems] = useState<WantItem[] | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Which slot has an open target editor, and which has an open note editor.
  const [editingTarget, setEditingTarget] = useState<string | null>(null);
  const [editingNote, setEditingNote] = useState<string | null>(null);

  function load() {
    setState("loading");
    getWants()
      .then((rows) => {
        setItems(rows);
        setState("ready");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Couldn't load your want list.");
        setState("error");
      });
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRemove(item: WantItem) {
    setBusy(true);
    try {
      await removeWantItem(item.card_id, item.variant);
      setItems((prev) =>
        (prev ?? []).filter(
          (i) => !(i.card_id === item.card_id && i.variant === item.variant),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove the slot.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveTarget(item: WantItem, raw: string) {
    const trimmed = raw.trim();
    // Empty input clears the target (honest "no target"), never coerces to 0.
    if (trimmed === "") {
      return handleClearTarget(item);
    }
    const value = Number(trimmed);
    if (!Number.isFinite(value) || value < 0) {
      setError("Target price must be a non-negative number.");
      return;
    }
    setBusy(true);
    try {
      const updated = await patchWantItem(item.card_id, item.variant, {
        target_price: value,
      });
      setItems((prev) =>
        (prev ?? []).map((i) =>
          i.card_id === item.card_id && i.variant === item.variant ? updated : i,
        ),
      );
      setEditingTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the target.");
    } finally {
      setBusy(false);
    }
  }

  async function handleClearTarget(item: WantItem) {
    setBusy(true);
    try {
      const updated = await patchWantItem(item.card_id, item.variant, {
        target_price: null,
      });
      setItems((prev) =>
        (prev ?? []).map((i) =>
          i.card_id === item.card_id && i.variant === item.variant ? updated : i,
        ),
      );
      setEditingTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't clear the target.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveNote(item: WantItem, raw: string) {
    const next = raw.trim() === "" ? null : raw;
    setBusy(true);
    try {
      const updated = await patchWantItem(item.card_id, item.variant, { note: next });
      setItems((prev) =>
        (prev ?? []).map((i) =>
          i.card_id === item.card_id && i.variant === item.variant ? updated : i,
        ),
      );
      setEditingNote(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the note.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading") {
    return (
      <section className="wants">
        <div className="skeleton skeleton-block" aria-label="Loading want list" />
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="wants">
        <p className="error">{error}</p>
        <button className="link" onClick={load}>Try again</button>
      </section>
    );
  }

  const list = items ?? [];

  if (list.length === 0) {
    return (
      <section className="wants">
        <p className="muted">
          Your want list is empty. Add cards from any card detail (the “Hunt this card”
          button) to track cards you’re looking for — each slot carries an optional
          target price and is compared to the same proven market price the rest of the
          app uses, never a fabricated figure.
        </p>
      </section>
    );
  }

  return (
    <section className="wants">
      <div className="wants-toolbar">
        <span className="muted small">{list.length} card(s)</span>
      </div>
      {error && <p className="error small">{error}</p>}
      <p className="muted small wants-hint">
        Each market price is the same proven reference the rest of the app uses — a
        slot with no market price is shown honestly, never a fabricated figure. A
        deal gap is only shown when both a target and a market price are present.
      </p>

      <div className="wants-grid">
        {list.map((item) => (
          <WantSlot
            key={`${item.card_id}|${item.variant}`}
            item={item}
            busy={busy}
            editingTarget={editingTarget === `${item.card_id}|${item.variant}`}
            editingNote={editingNote === `${item.card_id}|${item.variant}`}
            onStartEditTarget={() => setEditingTarget(`${item.card_id}|${item.variant}`)}
            onCancelEditTarget={() => setEditingTarget(null)}
            onSaveTarget={(v) => void handleSaveTarget(item, v)}
            onClearTarget={() => void handleClearTarget(item)}
            onStartEditNote={() => setEditingNote(`${item.card_id}|${item.variant}`)}
            onCancelEditNote={() => setEditingNote(null)}
            onSaveNote={(v) => void handleSaveNote(item, v)}
            onRemove={() => void handleRemove(item)}
          />
        ))}
      </div>
    </section>
  );
}

interface SlotProps {
  item: WantItem;
  busy: boolean;
  editingTarget: boolean;
  editingNote: boolean;
  onStartEditTarget: () => void;
  onCancelEditTarget: () => void;
  onSaveTarget: (value: string) => void;
  onClearTarget: () => void;
  onStartEditNote: () => void;
  onCancelEditNote: () => void;
  onSaveNote: (value: string) => void;
  onRemove: () => void;
}

function WantSlot({
  item,
  busy,
  editingTarget,
  editingNote,
  onStartEditTarget,
  onCancelEditTarget,
  onSaveTarget,
  onClearTarget,
  onStartEditNote,
  onCancelEditNote,
  onSaveNote,
  onRemove,
}: SlotProps) {
  const [targetDraft, setTargetDraft] = useState(
    item.target_price != null ? String(item.target_price) : "",
  );
  const [noteDraft, setNoteDraft] = useState(item.note ?? "");

  useEffect(() => {
    setTargetDraft(item.target_price != null ? String(item.target_price) : "");
  }, [item.target_price]);
  useEffect(() => {
    setNoteDraft(item.note ?? "");
  }, [item.note]);

  const img = item.image_large ?? item.image_small ?? null;

  return (
    <div className="wants-slot">
      {img ? (
        <img className="wants-img" src={img} alt={item.card_name} loading="lazy" />
      ) : (
        <div className="wants-img ph">no image</div>
      )}
      <div className="wants-slot-meta">
        <strong className="wants-name">{item.card_name}</strong>
        <div className="muted small">
          {item.set_name} · #{item.number}
          {item.rarity ? ` · ${item.rarity}` : ""}
          {item.variant && item.variant !== "normal" ? ` · ${item.variant}` : ""}
        </div>

        <MarketPriceChip item={item} />

        <TargetEditor
          item={item}
          editing={editingTarget}
          draft={targetDraft}
          setDraft={setTargetDraft}
          busy={busy}
          onStart={onStartEditTarget}
          onCancel={onCancelEditTarget}
          onSave={onSaveTarget}
          onClear={onClearTarget}
        />

        <DealGapChip item={item} />

        {editingNote ? (
          <div className="wants-note-edit">
            <input
              className="wants-note-input"
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="Add a note (optional)"
              aria-label={`Note for ${item.card_name}`}
            />
            <button className="link" onClick={() => onSaveNote(noteDraft)} disabled={busy}>
              Save note
            </button>
            <button className="link" onClick={onCancelEditNote} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : (
          <div className="wants-note-row">
            {item.note ? (
              <span className="wants-note">{item.note}</span>
            ) : (
              <button className="link wants-note-add" onClick={onStartEditNote}>
                Add a note
              </button>
            )}
            {item.note && (
              <button className="link" onClick={onStartEditNote}>
                Edit note
              </button>
            )}
          </div>
        )}

        <div className="wants-slot-actions">
          <button className="link wants-remove" onClick={onRemove} disabled={busy}>
            Remove from wants
          </button>
        </div>
      </div>
    </div>
  );
}

function MarketPriceChip({ item }: { item: WantItem }) {
  if (item.market_price != null) {
    return (
      <div className="wants-market">
        <span className="wants-market-price">{formatMoney(item.market_price)}</span>
        <span className="muted small">
          {item.market_source ? ` · ${item.market_source}` : ""}
          {item.market_source_updated_at ? ` · ${item.market_source_updated_at}` : ""}
        </span>
      </div>
    );
  }
  return <p className="wants-market none muted small">No market price yet.</p>;
}

interface TargetEditorProps {
  item: WantItem;
  editing: boolean;
  draft: string;
  setDraft: (v: string) => void;
  busy: boolean;
  onStart: () => void;
  onCancel: () => void;
  onSave: (value: string) => void;
  onClear: () => void;
}

function TargetEditor({
  item,
  editing,
  draft,
  setDraft,
  busy,
  onStart,
  onCancel,
  onSave,
  onClear,
}: TargetEditorProps) {
  if (editing) {
    return (
      <div className="wants-target-edit">
        <input
          className="wants-target-input"
          type="number"
          min={0}
          step="any"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Target price (optional)"
          aria-label={`Target price for ${item.card_name}`}
        />
        <button className="link" onClick={() => onSave(draft)} disabled={busy}>
          Save target
        </button>
        <button className="link" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    );
  }
  return (
    <div className="wants-target-row">
      {item.target_price != null ? (
        <>
          <span className="wants-target">
            Target <strong>{formatMoney(item.target_price)}</strong>
          </span>
          <button className="link" onClick={onStart} disabled={busy}>
            Edit target
          </button>
          <button className="link" onClick={onClear} disabled={busy}>
            Clear target
          </button>
        </>
      ) : (
        <button className="link wants-target-set" onClick={onStart} disabled={busy}>
          Set target
        </button>
      )}
    </div>
  );
}

function DealGapChip({ item }: { item: WantItem }) {
  // Only show a deal gap when BOTH a target and a market price are present —
  // never a guess. A null gap (one side missing) is honest silence.
  if (item.deal_gap == null || item.target_price == null || item.market_price == null) {
    return null;
  }
  const within = item.within_target === true;
  const cls = within ? "ok" : "down";
  const label = within
    ? `Under your target by ${formatMoney(Math.abs(item.deal_gap))}`
    : `Over your target by ${formatMoney(Math.abs(item.deal_gap))}`;
  return <p className={`wants-dealgap ${cls} small`}>{label}</p>;
}