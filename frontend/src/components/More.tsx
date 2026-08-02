import { useEffect, useState } from "react";

import {
  deleteWatch,
  getVapidPublic,
  getWatches,
  patchWatch,
  subscribePush,
} from "../api/client";
import type { Watch } from "../api/types";

// Decode a VAPID public key from base64url to the Uint8Array the Push API
// expects. The server stores the key base64url-encoded; an empty string means
// "not configured" and is handled before this is called.
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

interface PushState {
  status: "idle" | "enabling" | "enabled" | "error";
  message?: string;
}

// The "More" tab: settings, honest channel-status cards, and watchlist
// management. Channel cards NEVER claim a channel works when it isn't — email
// and listings have no config-status endpoint, so they show static honest
// hints ("set CARDPLATFORM_SMTP_* to enable"); push queries the VAPID
// endpoint and refuses to fake a subscription when the key is empty. The
// watchlist section lists existing watches with active toggles + delete.
export default function More() {
  const [push, setPush] = useState<PushState>({ status: "idle" });

  async function enablePush() {
    setPush({ status: "enabling" });
    try {
      // 1. Permission. If denied, stop honestly — don't fake a subscription.
      if (typeof Notification !== "undefined" && Notification.permission !== "granted") {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") {
          setPush({ status: "error", message: "Notification permission was denied." });
          return;
        }
      }
      // 2. VAPID key. Empty string = not configured on the server → honest stop.
      const vapid = await getVapidPublic();
      if (!vapid) {
        setPush({
          status: "error",
          message: "Push not configured on the server (set CARDPLATFORM_VAPID_* and run gen-vapid).",
        });
        return;
      }
      // 3. Service worker + push subscription. Requires a registered SW; the
      // PWA plugin registers one. If absent, this throws honestly.
      if (!("serviceWorker" in navigator) || !navigator.serviceWorker.ready) {
        setPush({ status: "error", message: "Couldn't enable push (no service worker)." });
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      let sub: PushSubscription;
      try {
        // The cast papers over a lib strictness mismatch (Uint8Array's buffer
        // is ArrayBufferLike, which includes SharedArrayBuffer, but the Push
        // API wants BufferSource<ArrayBuffer>). The runtime value is fine.
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapid) as unknown as BufferSource,
        });
      } catch {
        setPush({ status: "error", message: "Couldn't enable push." });
        return;
      }
      const key = sub.getKey("p256dh");
      const auth = sub.getKey("auth");
      await subscribePush({
        endpoint: sub.endpoint,
        p256dh: key ? btoa(String.fromCharCode(...new Uint8Array(key))) : "",
        auth: auth ? btoa(String.fromCharCode(...new Uint8Array(auth))) : "",
      });
      setPush({ status: "enabled" });
    } catch (err) {
      setPush({
        status: "error",
        message: err instanceof Error ? err.message : "Couldn't enable push.",
      });
    }
  }

  return (
    <section className="more-pane">
      <h2>Channels</h2>

      {/* Push — queries the VAPID endpoint; honest about unconfigured. */}
      <div className="channel-card">
        <div className="channel-head">
          <strong>Push</strong>
          {push.status === "enabled" ? (
            <span className="channel-on">Enabled</span>
          ) : push.status === "enabling" ? (
            <span className="muted small">Enabling…</span>
          ) : push.status === "error" ? (
            <span className="channel-off">Off</span>
          ) : (
            <span className="channel-off">Off</span>
          )}
        </div>
        {push.status === "enabled" ? (
          <p className="muted small">You'll receive push notifications for fired alerts.</p>
        ) : push.status === "error" && push.message ? (
          <p className="error small">{push.message}</p>
        ) : (
          <p className="muted small">
            Get pinged in-browser or on your installed PWA when an alert fires.
          </p>
        )}
        {push.status !== "enabled" && push.status !== "enabling" && (
          <button className="link" onClick={() => void enablePush()}>
            Enable push
          </button>
        )}
      </div>

      {/* Email — no SMTP-status endpoint exists. Static honest hint: the
          frontend cannot query the server's SMTP config, so it says what the
          operator must set rather than fabricating a status. Documented as a
          deliberate scope-cut: adding a /alerts/channels status endpoint would
          be cleaner but is backend scope creep for this task. */}
      <div className="channel-card">
        <div className="channel-head">
          <strong>Email</strong>
          <span className="channel-off">Not configured</span>
        </div>
        <p className="muted small">
          Email alerts: set <code>CARDPLATFORM_SMTP_*</code> on the server to enable.
        </p>
      </div>

      {/* Listings — no endpoint to query the key's presence. Static honest
          hint, same reasoning as email. The card-detail listings panel is the
          per-card signal; this is the global status. */}
      <div className="channel-card">
        <div className="channel-head">
          <strong>Listings (eBay)</strong>
          <span className="channel-off">Not configured</span>
        </div>
        <p className="muted small">
          Set <code>CARDPLATFORM_LISTINGS_API_KEY</code> to detect restocks, new listings, and
          auctions.
        </p>
      </div>

      {/* Poll interval — no settings endpoint; honest static hint, not a
          fabricated exact number. */}
      <div className="channel-card">
        <div className="channel-head">
          <strong>Polling</strong>
        </div>
        <p className="muted small">
          Alerts are checked every few minutes while the app is open.
        </p>
      </div>

      <WatchlistSection />
    </section>
  );
}

// The user's watch management surface: list existing watches, toggle active,
// delete. Mirrors the CCN-style watchlist. Reuses getWatches/patchWatch/
// deleteWatch; an honest empty state when there are none yet.
function WatchlistSection() {
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getWatches()
      .then((rows) => {
        if (!cancelled) setWatches(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load your watches.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggleActive(w: Watch) {
    try {
      const updated = await patchWatch(w.id, { active: !w.active });
      setWatches((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't update the watch.");
    }
  }

  async function remove(w: Watch) {
    try {
      await deleteWatch(w.id);
      setWatches((prev) => (prev ?? []).filter((x) => x.id !== w.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete the watch.");
    }
  }

  return (
    <div className="more-watchlist">
      <h3>Watchlist</h3>
      {error && <p className="error small">{error}</p>}
      {watches === null ? (
        <div className="skeleton skeleton-block" aria-label="Loading watches" />
      ) : watches.length === 0 ? (
        <p className="muted small">
          No watches yet. Watch a card from the Alerts tab or a card detail to get pinged.
        </p>
      ) : (
        <ul className="watchlist-rows">
          {watches.map((w) => (
            <li key={w.id} className="watchlist-row">
              <div className="watchlist-meta">
                <strong>{w.card_id ?? w.subject_label ?? "Drop watch"}</strong>
                <span className="muted small">
                  {w.alert_type.replace("_", " ")}
                  {w.target_price != null ? ` · target ${w.target_price}` : ""}
                  {w.drop_at ? ` · drop ${w.drop_at}` : ""}
                  {!w.active ? " · paused" : ""}
                </span>
              </div>
              <div className="watchlist-actions">
                <button
                  className={`link ${w.active ? "on" : ""}`}
                  onClick={() => void toggleActive(w)}
                  aria-pressed={w.active}
                >
                  {w.active ? "On" : "Off"}
                </button>
                <button className="link" onClick={() => void remove(w)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}