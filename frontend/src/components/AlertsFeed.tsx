import { useCallback, useEffect, useState } from "react";

import { getAlerts, markAlertRead, readAllAlerts } from "../api/client";
import type { AlertEvent, AlertType } from "../api/types";
import { relativeTime } from "../lib/time";

interface Props {
  onOpenCard: (card: { cardId: string; variant?: string }) => void;
  onWatchCard: (card?: { cardId?: string; variant?: string }) => void;
}

// One filter chip per alert_type plus "All". The chip label is short for the
// crowded mobile nav; the underlying filter value is the alert_type string
// (or null for All). Kept in one place so the picker and the row icon stay in
// lockstep.
type Filter = AlertType | "all";

const CHIPS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "restock", label: "Restock" },
  { value: "new_listing", label: "New listing" },
  { value: "price_target", label: "Price" },
  { value: "auction_ending", label: "Auction" },
  { value: "drop_time", label: "Drops" },
  { value: "deal", label: "Deals" },
];

// A small icon per alert_type. Emojis match the spec (📦 ✨ 🎯 ⏳ ⏰); they read
// fine on a dark theme and avoid a per-type colored-dot legend.
const ICON: Record<AlertType, string> = {
  restock: "📦",
  new_listing: "✨",
  price_target: "🎯",
  auction_ending: "⏳",
  drop_time: "⏰",
  deal: "💰",
};

// The context field is a free-form string. The engine may JSON-encode a url
// (e.g. a listing link); try to parse it for a deep link, and fall back to
// treating a bare http(s) string as a url. Never fabricate a link when the
// field is empty or unparseable.
function contextUrl(context: string | null): string | null {
  if (!context) return null;
  if (context.startsWith("http")) return context;
  try {
    const parsed = JSON.parse(context) as { url?: string };
    if (parsed?.url) return parsed.url;
  } catch {
    // Not JSON and not a bare url — no deep link.
  }
  return null;
}

export default function AlertsFeed({ onOpenCard, onWatchCard }: Props) {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await getAlerts({ limit: 100 });
      setEvents(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load alerts.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function handleRowClick(ev: AlertEvent) {
    // Mark read first (local optimistic update), then open the deep link.
    if (ev.read_at === null) {
      setEvents((prev) =>
        prev.map((e) => (e.id === ev.id ? { ...e, read_at: new Date().toISOString() } : e)),
      );
      try {
        await markAlertRead(ev.id);
      } catch {
        // Optimistic update stays — the row is still opened; a failed mark
        // is not worth blocking the navigation. The next refresh will
        // re-sync read_at from the server.
      }
    }
    if (ev.card_id) {
      onOpenCard({ cardId: ev.card_id, variant: undefined });
      return;
    }
    const url = contextUrl(ev.context);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  async function handleReadAll() {
    try {
      await readAllAlerts();
      setEvents((prev) =>
        prev.map((e) => (e.read_at === null ? { ...e, read_at: new Date().toISOString() } : e)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't mark all read.");
    }
  }

  const filtered = filter === "all" ? events : events.filter((e) => e.alert_type === filter);
  const hasUnread = events.some((e) => e.read_at === null);

  if (loading) {
    return (
      <section className="alerts-feed">
        <div className="skeleton skeleton-block" aria-label="Loading alerts" />
      </section>
    );
  }

  if (error) {
    return (
      <section className="alerts-feed">
        <p className="error">{error}</p>
        <button className="link" onClick={() => void load()}>
          Retry
        </button>
      </section>
    );
  }

  // HONEST empty state: truly no events. The radar copy + a "Watch a card" CTA
  // that opens the sheet. NEVER fabricate an event.
  if (events.length === 0) {
    return (
      <section className="alerts-feed alerts-empty">
        <p className="alerts-radar">
          Your personal card-market radar — watch a card to get pinged the moment it restocks, hits
          your price, or a vending machine drops.
        </p>
        <button className="primary" onClick={() => onWatchCard()}>
          Watch a card
        </button>
      </section>
    );
  }

  return (
    <section className="alerts-feed">
      <div className="alerts-toolbar">
        <div className="alert-chips" role="tablist" aria-label="Filter alerts by type">
          {CHIPS.map((c) => (
            <button
              key={c.value}
              className={`alert-chip${filter === c.value ? " selected" : ""}`}
              role="tab"
              aria-selected={filter === c.value}
              onClick={() => setFilter(c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="alerts-actions">
          {hasUnread && (
            <button className="link" onClick={() => void handleReadAll()}>
              Mark all read
            </button>
          )}
          <button className="link" onClick={() => void load()} aria-label="Refresh alerts">
            Refresh
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="muted small">No {filter === "all" ? "" : CHIPS.find((c) => c.value === filter)?.label.toLowerCase()} alerts right now.</p>
      ) : (
        <ul className="alert-list">
          {filtered.map((ev) => (
            <li key={ev.id}>
              <button
                className={`alert-row${ev.read_at === null ? " unread" : ""}`}
                onClick={() => void handleRowClick(ev)}
              >
                <span className="alert-icon" aria-hidden="true">
                  {ICON[ev.alert_type]}
                </span>
                <span className="alert-body">
                  <span className="alert-message">{ev.message}</span>
                  <span className="alert-meta muted small">
                    {relativeTime(ev.created_at)}
                    {ev.delivered_push ? " · 🔔" : ""}
                    {ev.delivered_email ? " · ✉️" : ""}
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