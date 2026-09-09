import { useState } from "react";

import type { InstallOutcome } from "../lib/useInstallPrompt";

// The install surface for the More tab. Three honest branches, never a fake
// "installed" claim:
//   1. canInstall — Chromium captured beforeinstallprompt; show the button.
//   2. iosInstructions — iOS never fires that event; show Share-sheet steps.
//   3. installed — running standalone; render nothing (no point offering it).
// After a Chromium prompt resolves, surface the outcome (added / dismissed)
// honestly rather than leaving the button dangling.
//
// Props-driven (not hook-coupled) so it tests as a pure function of state; the
// More tab wires the real useInstallPrompt hook to these props.
export default function InstallCard({
  canInstall,
  iosInstructions,
  installed,
  onInstall,
}: {
  canInstall: boolean;
  iosInstructions: boolean;
  installed: boolean;
  onInstall: () => Promise<InstallOutcome>;
}) {
  const [outcome, setOutcome] = useState<InstallOutcome | null>(null);
  const [busy, setBusy] = useState(false);

  if (installed) return null;

  if (iosInstructions) {
    return (
      <div className="channel-card install-card">
        <div className="channel-head">
          <strong>Install app</strong>
          <span className="channel-off">Add to Home Screen</span>
        </div>
        <p className="muted small">
          On iPhone/iPad, tap the <strong>Share</strong> icon in Safari, then
          <strong> Add to Home Screen</strong> to install Card Scan as a
          full-screen app.
        </p>
      </div>
    );
  }

  if (!canInstall) return null;

  async function handleInstall() {
    setBusy(true);
    const result = await onInstall();
    setOutcome(result);
    setBusy(false);
  }

  return (
    <div className="channel-card install-card">
      <div className="channel-head">
        <strong>Install app</strong>
        <span className="channel-on">Ready</span>
      </div>
      {outcome === "accepted" ? (
        <p className="muted small">Added to your Home Screen — launch it from there any time.</p>
      ) : outcome === "dismissed" ? (
        <p className="muted small">Maybe later. You can install any time from this tab.</p>
      ) : outcome === "error" ? (
        <p className="error small">Couldn't start the install prompt. Try again from this tab.</p>
      ) : (
        <p className="muted small">
          Install Card Scan as a full-screen app on this device for offline-friendly access.
        </p>
      )}
      {outcome === null && (
        <button className="link" disabled={busy} onClick={() => void handleInstall()}>
          {busy ? "Opening…" : "Install app"}
        </button>
      )}
    </div>
  );
}