import { useEffect, useState } from "react";

import { getResolvedPrice, refreshPrice } from "../api/client";
import type { Price } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

interface Props {
  cardId: string;
  variant: string;
  initial: Price | null;
  /** Show the low/mid/high provenance band + a clearer source label. Compact line
   *  by default (scan result); the band is the card-detail view's richer read. */
  showBand?: boolean;
}

type State = "idle" | "loading" | "fetching" | "none";

// Raw source strings ("tcgplayer" / "cardmarket") are opaque to a user. The card
// detail view labels them so the figure is legible as a market reference vs a fallback.
function sourceLabel(source: string): string {
  if (source === "tcgplayer") return "TCGplayer market reference";
  if (source === "cardmarket") return "Cardmarket aggregate";
  return source;
}

export default function PriceLine({ cardId, variant, initial, showBand = false }: Props) {
  const [price, setPrice] = useState<Price | null>(initial);
  const [state, setState] = useState<State>(initial ? "idle" : "loading");

  useEffect(() => {
    let cancelled = false;
    if (initial) return;

    async function load() {
      const cached = await getResolvedPrice(cardId, variant).catch(() => null);
      if (cancelled) return;
      if (cached) {
        setPrice(cached);
        setState("idle");
        return;
      }
      // Nothing cached: only 2 of 20,444 cards were priced at build time, so this is
      // the normal path, and at 4.3s mean it is slow enough to deserve its own message.
      setState("fetching");
      const fresh = await refreshPrice(cardId, variant).catch(() => null);
      if (cancelled) return;
      setPrice(fresh);
      setState(fresh ? "idle" : "none");
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [cardId, variant, initial]);

  if (state === "loading") return <p className="price muted">Checking price…</p>;
  if (state === "fetching") return <p className="price muted">Fetching live price…</p>;
  if (!price) return <p className="price muted">No price available</p>;

  if (showBand) {
    // The card-detail view's richer read: market figure plus the low/mid/high band
    // and a legible source label. Every figure carries source + staleness, so a
    // number is never shown without saying where it came from.
    return (
      <p className="price price-band">
        <strong>{formatMoney(price.market)}</strong>
        <span className="price-meta">
          {sourceLabel(price.source)} · {formatStaleness(price.source_updated_at)}
        </span>
        <span className="price-band-range muted small">
          low {formatMoney(price.low)} · mid {formatMoney(price.mid)} · high {formatMoney(price.high)}
        </span>
      </p>
    );
  }

  return (
    <p className="price">
      <strong>{formatMoney(price.market)}</strong>
      <span className="price-meta">
        {price.source} · {formatStaleness(price.source_updated_at)}
      </span>
    </p>
  );
}
