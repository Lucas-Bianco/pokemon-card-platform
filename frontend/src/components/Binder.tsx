import { useEffect, useState } from "react";

import {
  exportBinder,
  getBinder,
  removeBinderItem,
  reorderBinder,
  setBinderNote,
} from "../api/client";
import type { BinderItem } from "../api/types";
import { formatMoney } from "../lib/format";

// The Binder tab (roadmap row 21): a curated, ordered subset of your vault you
// show off. NOT a second copy of the collection — a thin ordered reference list
// of (card, variant) slots, each joined to its catalog row + single most-recent
// *proven* eBay sale at read time.
//
// HONESTY (the whole feature):
// - `proven_sale` is the whole object or null: a slot with no proven sale shows
//   "No proven sale yet" (or "set an eBay key to prove sales" when no key is
//   configured), NEVER a fabricated $0.
// - "Export binder" downloads a standalone self-contained HTML document (inline
//   CSS, hotlinked images, proven-sale line per card). That file is the
//   shareable artifact — you host/attach it anywhere; no server uptime required.
// - Move up/down reorders via POST /binder/reorder (the full new order); Remove
//   via DELETE; note edit via PATCH. All surface honest inline errors.
//
// Do-not-break: no button here is named "Scan", and no CTA collides with a nav
// tab label — "Export binder" / "Print binder" / "Move up" / "Move down" /
// "Remove" / "Save note" are all distinct verb-phrases.

type LoadState = "loading" | "ready" | "error";

function soldDate(iso: string | null): string {
  if (!iso) return "recently";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "recently";
  return d.toISOString().slice(0, 10);
}

export default function Binder() {
  const [items, setItems] = useState<BinderItem[] | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  function load() {
    setState("loading");
    getBinder()
      .then((rows) => {
        setItems(rows);
        setState("ready");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Couldn't load your binder.");
        setState("error");
      });
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRemove(item: BinderItem) {
    setBusy(true);
    try {
      await removeBinderItem(item.card_id, item.variant);
      setItems((prev) => (prev ?? []).filter((i) => !(i.card_id === item.card_id && i.variant === item.variant)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove the slot.");
    } finally {
      setBusy(false);
    }
  }

  async function handleMove(item: BinderItem, dir: -1 | 1) {
    const list = items ?? [];
    const idx = list.findIndex((i) => i.card_id === item.card_id && i.variant === item.variant);
    const target = idx + dir;
    if (idx < 0 || target < 0 || target >= list.length) return;
    // New full order: swap the two adjacent slots.
    const reordered = [...list];
    [reordered[idx], reordered[target]] = [reordered[target], reordered[idx]];
    setBusy(true);
    try {
      await reorderBinder({
        items: reordered.map((i) => ({ card_id: i.card_id, variant: i.variant })),
      });
      setItems(reordered);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reorder the binder.");
      // Revert optimistically-held order by reloading.
      load();
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveNote(item: BinderItem, value: string) {
    const next = value.trim() === "" ? null : value;
    setBusy(true);
    try {
      await setBinderNote(item.card_id, item.variant, { note: next });
      setItems((prev) =>
        (prev ?? []).map((i) =>
          i.card_id === item.card_id && i.variant === item.variant ? { ...i, note: next } : i,
        ),
      );
      setNote(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the note.");
    } finally {
      setBusy(false);
    }
  }

  async function handleExport() {
    setBusy(true);
    try {
      const html = await exportBinder();
      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "binder.html";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't export the binder.");
    } finally {
      setBusy(false);
    }
  }

  async function handlePrint() {
    // Open the standalone HTML in a new window and print it — the printed page
    // is the curated binder document, not the app shell. Guarded for jsdom /
    // popup-blocked environments (window.open returns null there).
    setBusy(true);
    try {
      const html = await exportBinder();
      const w = window.open("", "_blank");
      if (!w) {
        setError("Couldn't open a print window (popup blocked?). Use Export instead.");
        return;
      }
      w.document.open();
      w.document.write(html);
      w.document.close();
      w.focus();
      w.print();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't print the binder.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading") {
    return (
      <section className="binder">
        <div className="skeleton skeleton-block" aria-label="Loading binder" />
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="binder">
        <p className="error">{error}</p>
        <button className="link" onClick={load}>Try again</button>
      </section>
    );
  }

  const list = items ?? [];

  if (list.length === 0) {
    return (
      <section className="binder">
        <p className="muted">Your binder is empty.</p>
        <p className="muted small binder-lede">
          A binder is a curated, ordered subset of your vault you show off — each price
          shown is a proven eBay sale, never a fabricated figure.
        </p>
        <ol className="binder-howto">
          <li>Scan a card, or open any card already in your vault.</li>
          <li>
            Tap <strong>Add to binder</strong> on that card to pin it here, in the order you
            want it shown.
          </li>
          <li>
            <strong>Export binder</strong> or <strong>Print binder</strong> above to share it
            — the export is a standalone HTML file you host or attach anywhere.
          </li>
        </ol>
      </section>
    );
  }

  // Proven-coverage summary: how many of the displayed slots are actually
  // backed by a proven eBay sale. Honest counts only — never a summed $ value
  // (summing disparate single sales would imply a portfolio value the binder
  // is not). A slot counts as "proven" when proven_sale is a real object; the
  // unavailable (no eBay key) and empty (no sale yet) cases do not.
  const provenCount = list.filter((i) => i.proven_sale !== null).length;
  const provenLabel =
    provenCount === 0
      ? "none proven yet"
      : provenCount === list.length
        ? "all proven"
        : `${provenCount} of ${list.length} proven`;

  return (
    <section className="binder">
      <div className="binder-toolbar">
        <span className="muted small binder-count">
          {list.length} card{list.length === 1 ? "" : "s"} · {provenLabel}
        </span>
        <button className="link binder-export" onClick={() => void handleExport()} disabled={busy}>
          Export binder
        </button>
        <button className="link binder-print" onClick={() => void handlePrint()} disabled={busy}>
          Print binder
        </button>
      </div>
      {error && <p className="error small">{error}</p>}
      <p className="muted small binder-note-hint">
        Each price is a proven eBay sale — an actual transaction, not a listed ask. A slot
        with no proven sale is shown honestly, never a fabricated figure.
      </p>

      <div className="binder-grid">
        {list.map((item, i) => (
          <BinderSlot
            key={`${item.card_id}|${item.variant}`}
            item={item}
            first={i === 0}
            last={i === list.length - 1}
            busy={busy}
            editingNote={note === `${item.card_id}|${item.variant}`}
            onStartEditNote={() => setNote(`${item.card_id}|${item.variant}`)}
            onCancelNote={() => setNote(null)}
            onSaveNote={(v) => void handleSaveNote(item, v)}
            onMoveUp={() => void handleMove(item, -1)}
            onMoveDown={() => void handleMove(item, 1)}
            onRemove={() => void handleRemove(item)}
          />
        ))}
      </div>
    </section>
  );
}

interface SlotProps {
  item: BinderItem;
  first: boolean;
  last: boolean;
  busy: boolean;
  editingNote: boolean;
  onStartEditNote: () => void;
  onCancelNote: () => void;
  onSaveNote: (value: string) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}

function BinderSlot({
  item,
  first,
  last,
  busy,
  editingNote,
  onStartEditNote,
  onCancelNote,
  onSaveNote,
  onMoveUp,
  onMoveDown,
  onRemove,
}: SlotProps) {
  const [draft, setDraft] = useState(item.note ?? "");
  useEffect(() => {
    setDraft(item.note ?? "");
  }, [item.note]);

  const img = item.image_large ?? item.image_small ?? null;

  return (
    <div className="binder-slot">
      {img ? (
        <img className="binder-img" src={img} alt={item.card_name} loading="lazy" />
      ) : (
        <div className="binder-img ph">no image</div>
      )}
      <div className="binder-slot-meta">
        <strong className="binder-name">{item.card_name}</strong>
        <div className="muted small">
          {item.set_name} · #{item.number}
          {item.rarity ? ` · ${item.rarity}` : ""}
          {item.variant && item.variant !== "normal" ? ` · ${item.variant}` : ""}
        </div>

        {editingNote ? (
          <div className="binder-note-edit">
            <input
              className="binder-note-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Add a note (optional)"
              aria-label={`Note for ${item.card_name}`}
            />
            <button className="link" onClick={() => onSaveNote(draft)} disabled={busy}>
              Save note
            </button>
            <button className="link" onClick={onCancelNote} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : (
          <div className="binder-note-row">
            {item.note ? (
              <span className="binder-note">{item.note}</span>
            ) : (
              <button className="link binder-note-add" onClick={onStartEditNote}>
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

        <ProvenSaleChip item={item} />

        <div className="binder-slot-actions">
          <button className="link" onClick={onMoveUp} disabled={busy || first}>
            Move up
          </button>
          <button className="link" onClick={onMoveDown} disabled={busy || last}>
            Move down
          </button>
          <button className="link binder-remove" onClick={onRemove} disabled={busy}>
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}

function ProvenSaleChip({ item }: { item: BinderItem }) {
  if (item.proven_sale) {
    const s = item.proven_sale;
    return (
      <div className="binder-sale">
        <span className="binder-sale-price">{formatMoney(s.price)}</span>
        <span className="muted small">
          {" "}· {soldDate(s.sold_at)}
          {s.condition ? ` · ${s.condition}` : ""}
          {s.url ? (
            <>
              {" · "}
              <a href={s.url} target="_blank" rel="noopener noreferrer">
                listing
              </a>
            </>
          ) : null}
        </span>
      </div>
    );
  }
  if (item.proven_sale_unavailable) {
    return <p className="binder-sale none muted small">No proven sale — set an eBay key to prove sales.</p>;
  }
  return <p className="binder-sale none muted small">No proven sale yet.</p>;
}