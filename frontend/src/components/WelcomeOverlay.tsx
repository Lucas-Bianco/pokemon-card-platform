import { motion } from "framer-motion";

// First-run onboarding overlay (Key mode). A brand-new user lands on a bare
// camera with no explanation of the scan → value → vault/binder loop; this
// surfaces that loop exactly once, the first time they reach Scan. Gated by
// lib/welcome.ts so it never nags, and dismissed by either the primary action
// or a Skip link — both call onDismiss (AppShell sets the flag + unmounts).
//
// The dismiss button is deliberately "Start scanning", NOT "Scan": the
// do-not-break contract requires exactly one button labeled "Scan" (the nav
// tab) across the whole app, so no other surface may reuse that label.
export default function WelcomeOverlay({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div
      className="welcome-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <motion.div
        className="welcome-card"
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.18, ease: "easeOut" }}
      >
        <h2 id="welcome-title">Welcome to Card Scan</h2>
        <p className="muted small">A local-first Pokémon card scanner. Here’s the loop:</p>

        <ol className="welcome-steps">
          <li>
            <span className="welcome-step-num" aria-hidden="true">1</span>
            <div className="welcome-step-body">
              <strong>Scan a card</strong>
              <span className="muted small">Point your camera at a card and capture it.</span>
            </div>
          </li>
          <li>
            <span className="welcome-step-num" aria-hidden="true">2</span>
            <div className="welcome-step-body">
              <strong>See its value, grade, and proven sales</strong>
              <span className="muted small">
                A market price backed by real eBay sold listings — never a guess.
              </span>
            </div>
          </li>
          <li>
            <span className="welcome-step-num" aria-hidden="true">3</span>
            <div className="welcome-step-body">
              <strong>Find it in your Vault, build your Binder</strong>
              <span className="muted small">Your collection, tracked and shareable.</span>
            </div>
          </li>
        </ol>

        <div className="welcome-actions">
          <button className="primary" onClick={onDismiss}>
            Start scanning
          </button>
          <button className="link" onClick={onDismiss}>
            Skip
          </button>
        </div>
      </motion.div>
    </div>
  );
}