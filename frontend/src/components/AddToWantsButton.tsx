import { useState } from "react";

import { addWantItem } from "../api/client";

// A self-contained "Hunt this card" affordance for CardDetail (and anywhere a
// card is in view). Calls POST /wants/items and surfaces honest inline status:
// "On your want list" on 201, "Already on your want list" on 409 (the backend's
// Conflict for a duplicate slot), "Card not found" on 404, or the verbatim
// thrown error otherwise — never a fabricated friendly fallback. Distinct
// verb-phrase from every nav tab AND from "Add to binder" (the do-not-break
// contract: tab labels and dashboard CTAs stay distinct; "Hunt this card"
// collides with nothing).
type Status = "idle" | "adding" | "added" | "error";

interface Props {
  cardId: string;
  variant?: string;
}

export default function AddToWantsButton({ cardId, variant = "normal" }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleAdd() {
    setStatus("adding");
    setMessage(null);
    try {
      await addWantItem({ card_id: cardId, variant });
      setStatus("added");
      setMessage("On your want list");
    } catch (err) {
      // expectJson throws `request failed: <status>`. 409 is the one status with
      // a clear semantic meaning here (the slot already exists) — surface that
      // meaning rather than the opaque code. 404 means the card isn't in the
      // catalog. Anything else surfaces verbatim — the real failure, not a
      // fabricated fallback (the same honest-error contract AddToBinderButton
      // follows).
      const text = err instanceof Error ? err.message : "Couldn't add to your want list.";
      if (text.includes("409")) {
        setStatus("error");
        setMessage("Already on your want list");
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
    <div className="add-to-wants">
      <button
        className="link add-to-wants-btn"
        onClick={() => void handleAdd()}
        disabled={disabled}
      >
        {status === "adding"
          ? "Adding…"
          : status === "added"
            ? "On want list ✓"
            : "Hunt this card"}
      </button>
      {message && (
        <span className={`add-to-wants-note ${status === "error" ? "err" : "ok"}`}>
          {message}
        </span>
      )}
    </div>
  );
}