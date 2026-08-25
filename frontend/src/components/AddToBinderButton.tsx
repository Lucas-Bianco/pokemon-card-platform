import { useState } from "react";

import { addBinderItem } from "../api/client";

// A self-contained "Add to binder" affordance for CardDetail (and anywhere a
// card is in view). Calls POST /binder/items and surfaces honest inline status:
// "Added to your binder" on 201, "Already in your binder" on 409 (the backend's
// Conflict for a duplicate slot), "Card not found" on 404, or the verbatim
// thrown error otherwise — never a fabricated friendly fallback. Distinct
// verb-phrase from every nav tab (the do-not-break contract: tab labels and
// dashboard CTAs stay distinct; "Add to binder" collides with nothing).
type Status = "idle" | "adding" | "added" | "error";

interface Props {
  cardId: string;
  variant?: string;
}

export default function AddToBinderButton({ cardId, variant = "normal" }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleAdd() {
    setStatus("adding");
    setMessage(null);
    try {
      await addBinderItem({ card_id: cardId, variant });
      setStatus("added");
      setMessage("Added to your binder");
    } catch (err) {
      // expectJson throws `request failed: <status>`. 409 is the one status with
      // a clear semantic meaning here (the slot already exists) — surface that
      // meaning rather than the opaque code. 404 means the card isn't in the
      // catalog. Anything else surfaces verbatim — the real failure, not a
      // fabricated fallback (the same honest-error contract the AlertsFeed pull
      // follows).
      const text = err instanceof Error ? err.message : "Couldn't add to binder.";
      if (text.includes("409")) {
        setStatus("error");
        setMessage("Already in your binder");
      } else if (text.includes("404")) {
        setStatus("error");
        setMessage("Card not found");
      } else {
        setStatus("error");
        setMessage(text);
      }
    }
  }

  const disabled = status === "adding" || status === "added";

  return (
    <div className="add-to-binder">
      <button
        className="link add-to-binder-btn"
        onClick={() => void handleAdd()}
        disabled={disabled}
      >
        {status === "adding" ? "Adding…" : status === "added" ? "In binder ✓" : "Add to binder"}
      </button>
      {message && (
        <span className={`add-to-binder-note ${status === "error" ? "err" : "ok"}`}>
          {message}
        </span>
      )}
    </div>
  );
}